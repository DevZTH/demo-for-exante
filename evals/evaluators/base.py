"""Shared evaluator contracts and LLM-judge plumbing."""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from evals.models.schemas import (
    ClientResponse,
    EvalTestCase,
    EvaluatorResult,
    EvaluatorThresholds,
    JsonValue,
    JudgeResult,
    LLMCallResult,
    ModelConfig,
    ResponseLimits,
    RuleConfig,
    TokenUsage,
    validate_client_response,
)
from evals.prompts.judge import JUDGE_PROMPT_VERSION

if TYPE_CHECKING:
    from evals.providers.llm import LLMProvider


@dataclass(slots=True)
class EvaluationContext:
    """All inputs an evaluator may use for one generated response.

    ``StructureEvaluator`` populates ``response`` after strict validation.  The
    other evaluators can also parse ``raw_response`` themselves, which keeps
    them convenient to use independently in tests and custom runners.
    """

    case: EvalTestCase
    raw_response: Any
    response: ClientResponse | None = None
    provider: LLMProvider | None = None
    judge_model: ModelConfig | None = None
    thresholds: EvaluatorThresholds = field(default_factory=EvaluatorThresholds)
    rules: RuleConfig = field(default_factory=RuleConfig)
    limits: ResponseLimits = field(default_factory=ResponseLimits)
    metadata: dict[str, JsonValue] = field(default_factory=dict)


class BaseEvaluator(ABC):
    """Async interface implemented by every evaluator."""

    name: str
    critical: bool = False

    @abstractmethod
    async def evaluate(self, context: EvaluationContext) -> EvaluatorResult:
        """Evaluate one response without mutating testcase configuration."""


class LLMJudgeEvaluator(BaseEvaluator, ABC):
    """Base for narrow provider-neutral LLM-as-a-judge evaluators."""

    default_threshold: float
    minimum_score: float
    maximum_score: float

    def __init__(self, *, threshold: float | None = None) -> None:
        if (
            threshold is not None
            and not self.minimum_score <= threshold <= self.maximum_score
        ):
            raise ValueError(
                f"{self.name} threshold must be between "
                f"{self.minimum_score:g} and {self.maximum_score:g}"
            )
        self.threshold = threshold

    async def evaluate(self, context: EvaluationContext) -> EvaluatorResult:
        response, invalid = ensure_response(context)
        if invalid is not None:
            return self._failure(
                "Judge skipped because the client response is invalid: " + invalid,
                error_type="invalid_client_response",
            )
        if context.provider is None:
            return self._failure(
                "Judge provider is not configured",
                error_type="missing_provider",
            )
        if context.judge_model is None:
            return self._failure(
                "Judge model is not configured",
                error_type="missing_judge_model",
            )
        assert response is not None

        threshold = self._threshold(context)
        prompt = self.build_prompt(context, response, threshold)

        try:
            call = await context.provider.invoke_judge(
                prompt=prompt,
                evaluator_name=self.name,
                model=context.judge_model,
            )
            call_result = _normalize_call_result(call)
            verdict = _parse_judge_result(call_result.content)
            self._validate_score(verdict.score)
        # A provider is an external plugin boundary and may raise arbitrary
        # exceptions. Converting them to a result keeps one case from aborting
        # the benchmark, as required by the runner contract.
        except Exception as exc:  # noqa: BLE001
            return self._failure(
                f"Judge evaluation failed: {exc}",
                error_type=type(exc).__name__,
                threshold=threshold,
            )

        passed = verdict.score >= threshold
        metadata: dict[str, Any] = {
            "threshold": threshold,
            "score_min": self.minimum_score,
            "score_max": self.maximum_score,
            "violations": verdict.violations,
            "judge_reported_passed": verdict.passed,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "judge_model": call_result.model or context.judge_model.name,
            "latency_seconds": call_result.latency_seconds,
            "usage": call_result.usage.model_dump(mode="json"),
        }
        if call_result.metadata:
            metadata["provider"] = call_result.metadata
        if verdict.passed != passed:
            metadata["judge_pass_overridden"] = True

        return EvaluatorResult(
            name=self.name,
            score=verdict.score,
            passed=passed,
            reason=verdict.reason,
            metadata=metadata,
        )

    @abstractmethod
    def build_prompt(
        self,
        context: EvaluationContext,
        response: ClientResponse,
        threshold: float,
    ) -> str:
        """Render the criterion-specific prompt."""

    def _threshold(self, context: EvaluationContext) -> float:
        value = self.threshold
        if value is None:
            value = getattr(context.thresholds, self.name, self.default_threshold)
        value = float(value)
        if not self.minimum_score <= value <= self.maximum_score:
            raise ValueError(
                f"{self.name} threshold must be between "
                f"{self.minimum_score:g} and {self.maximum_score:g}"
            )
        return value

    def _validate_score(self, score: float) -> None:
        if not math.isfinite(score):
            raise ValueError("judge score must be finite")
        if not self.minimum_score <= score <= self.maximum_score:
            raise ValueError(
                f"{self.name} judge score {score:g} is outside rubric "
                f"[{self.minimum_score:g}, {self.maximum_score:g}]"
            )

    def _failure(
        self,
        reason: str,
        *,
        error_type: str,
        threshold: float | None = None,
    ) -> EvaluatorResult:
        metadata: dict[str, JsonValue] = {
            "error_type": error_type,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
        }
        if threshold is not None:
            metadata["threshold"] = threshold
        return EvaluatorResult(
            name=self.name,
            score=None,
            passed=False,
            reason=reason,
            metadata=metadata,
        )


def ensure_response(
    context: EvaluationContext,
    *,
    limits: ResponseLimits | None = None,
) -> tuple[ClientResponse | None, str | None]:
    """Return a validated response and cache it on the mutable context."""

    configured_limits = limits or context.limits
    source: Any = (
        context.response if context.response is not None else context.raw_response
    )
    if isinstance(source, LLMCallResult):
        source = source.content

    try:
        response = validate_client_response(source, configured_limits)
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return None, _validation_reason(exc)

    context.response = response
    return response, None


def conversation_payload(context: EvaluationContext) -> dict[str, JsonValue]:
    """Serialize history plus the current sales message for a judge prompt."""

    return {
        "history": [
            message.model_dump(mode="json") for message in context.case.history
        ],
        "latest_sales_message": context.case.message,
    }


def behavior_contract(context: EvaluationContext) -> dict[str, JsonValue]:
    return {
        "expected_behavior": list(context.case.expected_behavior),
        "forbidden_behavior": list(context.case.forbidden_behavior),
        "expected_done": context.case.expected_done,
    }


def _parse_judge_result(value: Any) -> JudgeResult:
    if isinstance(value, JudgeResult):
        return value
    if isinstance(value, str):
        return JudgeResult.model_validate_json(value)
    if isinstance(value, (bytes, bytearray)):
        return JudgeResult.model_validate_json(value)
    if isinstance(value, Mapping):
        return JudgeResult.model_validate(dict(value))
    if hasattr(value, "model_dump"):
        return JudgeResult.model_validate(value.model_dump())
    raise TypeError("judge content must be JudgeResult, a mapping, or a JSON string")


def _normalize_call_result(value: Any) -> LLMCallResult:
    if isinstance(value, LLMCallResult):
        return value
    # This fallback makes small hand-written fakes ergonomic while preserving
    # the provider contract for production implementations.
    if hasattr(value, "content"):
        return LLMCallResult(
            content=value.content,
            model=getattr(value, "model", None),
            latency_seconds=getattr(value, "latency_seconds", None),
            usage=_coerce_usage(getattr(value, "usage", None)),
            metadata=getattr(value, "metadata", None) or {},
        )
    return LLMCallResult(content=value)


def _coerce_usage(value: Any) -> TokenUsage:
    if isinstance(value, TokenUsage):
        return value
    return TokenUsage.model_validate(value or {})


def _validation_reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        details: list[str] = []
        for error in exc.errors(include_url=False):
            location = (
                ".".join(str(part) for part in error.get("loc", ())) or "response"
            )
            details.append(f"{location}: {error.get('msg', 'invalid value')}")
        return "; ".join(details)
    return str(exc) or type(exc).__name__


__all__ = [
    "BaseEvaluator",
    "EvaluationContext",
    "LLMJudgeEvaluator",
    "behavior_contract",
    "conversation_payload",
    "ensure_response",
]

"""Concurrent, retrying, failure-isolated evaluation orchestration."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import BaseModel

from evals.evaluators import (
    BaseEvaluator,
    ConsistencyEvaluator,
    ConversationEvaluator,
    EvaluationContext,
    IntentionsEvaluator,
    PersonaEvaluator,
    RealismEvaluator,
    RulesEvaluator,
    StructureEvaluator,
)
from evals.models.schemas import (
    ClientResponse,
    ConversationMessage,
    EvalResult,
    EvalRun,
    EvalTestCase,
    EvaluatorResult,
    EvaluatorThresholds,
    JsonValue,
    LLMCallResult,
    ModelConfig,
    PersonaConfig,
    ResponseLimits,
    RuleConfig,
    TokenUsage,
)
from evals.observability import (
    CaseObservation,
    EvalObserver,
    NullEvalObserver,
    ResilientEvalObserver,
)
from evals.prompts.judge import JUDGE_PROMPT_VERSION
from evals.providers.llm import LLMProvider, ProviderError
from evals.report import finalize_run

logger = logging.getLogger(__name__)
T = TypeVar("T")


def default_evaluators(*, include_judges: bool = True) -> list[BaseEvaluator]:
    evaluators: list[BaseEvaluator] = [StructureEvaluator(), RulesEvaluator()]
    if include_judges:
        evaluators.extend(
            [
                PersonaEvaluator(),
                RealismEvaluator(),
                IntentionsEvaluator(),
                ConsistencyEvaluator(),
                ConversationEvaluator(),
            ]
        )
    return evaluators


class EvalRunner:
    """Run each case N times while bounding concurrent provider traffic."""

    def __init__(
        self,
        provider: LLMProvider,
        evaluators: Sequence[BaseEvaluator] | None = None,
        *,
        client_model: ModelConfig,
        judge_model: ModelConfig | None = None,
        judge_provider: LLMProvider | None = None,
        limits: ResponseLimits | None = None,
        rules: RuleConfig | None = None,
        thresholds: EvaluatorThresholds | None = None,
        concurrency: int = 5,
        observer: EvalObserver | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self.provider = provider
        self.judge_provider = judge_provider or provider
        self.client_model = client_model
        self.judge_model = judge_model
        self.evaluators = list(
            evaluators
            if evaluators is not None
            else default_evaluators(include_judges=judge_model is not None)
        )
        self.limits = limits or ResponseLimits()
        self.rules = rules or RuleConfig()
        self.thresholds = thresholds or EvaluatorThresholds()
        self.concurrency = concurrency
        self.observer: EvalObserver
        if observer is None:
            self.observer = NullEvalObserver()
        elif isinstance(observer, (NullEvalObserver, ResilientEvalObserver)):
            self.observer = observer
        else:
            self.observer = ResilientEvalObserver(observer)

    async def run(
        self,
        cases: Sequence[EvalTestCase],
        *,
        runs_per_case: int = 1,
        system_prompt: str,
        dataset_name: str = "custom",
        prompt_version: str = "local",
        dataset_version: str = "1.0",
        judge_prompt_version: str = JUDGE_PROMPT_VERSION,
    ) -> EvalRun:
        if runs_per_case < 1:
            raise ValueError("runs_per_case must be at least 1")
        if not system_prompt.strip():
            raise ValueError("system_prompt must not be blank")

        run_id = uuid.uuid4().hex
        semaphore = asyncio.Semaphore(self.concurrency)
        tasks = [
            self._bounded_evaluate(
                semaphore,
                case,
                run_index,
                system_prompt=system_prompt,
                dataset_name=dataset_name,
                eval_run_id=run_id,
                prompt_version=prompt_version,
                judge_prompt_version=judge_prompt_version,
            )
            for case in cases
            for run_index in range(1, runs_per_case + 1)
        ]
        results = list(await asyncio.gather(*tasks)) if tasks else []

        run = EvalRun(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc),
            client_model=self.client_model.name,
            judge_model=self.judge_model.name if self.judge_model else None,
            prompt_version=prompt_version,
            judge_prompt_version=judge_prompt_version,
            dataset=dataset_name,
            dataset_version=dataset_version,
            runs_per_case=runs_per_case,
            results=results,
            metadata={
                "concurrency": self.concurrency,
                "case_count": len(cases),
                "evaluator_names": [item.name for item in self.evaluators],
                "client_provider": self.client_model.provider,
                "judge_provider": (
                    self.judge_model.provider if self.judge_model else None
                ),
            },
        )
        finalized = finalize_run(run)
        try:
            self.observer.flush()
        except Exception:
            logger.warning("Evaluation observer flush failed", exc_info=True)
        return finalized

    async def evaluate_case(
        self,
        case: EvalTestCase,
        *,
        system_prompt: str,
        run_index: int = 1,
        dataset_name: str = "custom",
        prompt_version: str = "local",
        judge_prompt_version: str = JUDGE_PROMPT_VERSION,
    ) -> EvalResult:
        """Evaluate one execution, useful for pytest and custom pipelines."""
        return await self._evaluate_execution(
            case,
            run_index,
            system_prompt=system_prompt,
            dataset_name=dataset_name,
            eval_run_id=uuid.uuid4().hex,
            prompt_version=prompt_version,
            judge_prompt_version=judge_prompt_version,
        )

    async def _bounded_evaluate(
        self,
        semaphore: asyncio.Semaphore,
        case: EvalTestCase,
        run_index: int,
        **kwargs: Any,
    ) -> EvalResult:
        async with semaphore:
            try:
                return await self._evaluate_execution(case, run_index, **kwargs)
            except Exception as exc:  # Last-resort isolation for one execution.
                logger.exception("Unexpected failure in testcase %s", case.id)
                return self._error_result(case, run_index, exc)

    async def _evaluate_execution(
        self,
        case: EvalTestCase,
        run_index: int,
        *,
        system_prompt: str,
        dataset_name: str,
        eval_run_id: str,
        prompt_version: str,
        judge_prompt_version: str,
    ) -> EvalResult:
        started = time.perf_counter()
        usage: list[TokenUsage] = []
        case_observation_manager = self.observer.case(
            case=case,
            dataset=dataset_name,
            eval_run_id=eval_run_id,
            run_index=run_index,
            client_model=self.client_model.name,
            judge_model=self.judge_model.name if self.judge_model else None,
            prompt_version=prompt_version,
            judge_prompt_version=judge_prompt_version,
        )

        try:
            with case_observation_manager as observation:
                return await self._evaluate_observed(
                    case,
                    run_index,
                    system_prompt=system_prompt,
                    prompt_version=prompt_version,
                    observation=observation,
                    usage=usage,
                    started=started,
                )
        except Exception as exc:
            # Tracing is optional; if it failed before a provider response exists,
            # preserve a useful case-level result rather than aborting the run.
            logger.exception("Case %s failed before evaluation completed", case.id)
            return self._error_result(
                case,
                run_index,
                exc,
                latency=time.perf_counter() - started,
                usage=_merge_usage(usage),
            )

    async def _evaluate_observed(
        self,
        case: EvalTestCase,
        run_index: int,
        *,
        system_prompt: str,
        prompt_version: str,
        observation: CaseObservation,
        usage: list[TokenUsage],
        started: float,
    ) -> EvalResult:
        call_attempts = 0

        async def invoke_client() -> LLMCallResult:
            nonlocal call_attempts
            call_attempts += 1
            with observation.model_call(
                name="eval-client-response",
                model=self.client_model,
                input_data={
                    "persona": case.persona,
                    "history": case.history,
                    "message": case.message,
                    "prompt_version": prompt_version,
                },
                metadata={"testcase_id": case.id, "attempt": call_attempts},
            ) as call_observation:
                try:
                    call = await self.provider.invoke_client(
                        system_prompt=system_prompt,
                        persona=case.persona,
                        history=case.history,
                        message=case.message,
                        model=self.client_model,
                    )
                    normalized = _normalize_call_result(call)
                    call_observation.finish(normalized)
                    return normalized
                except BaseException as exc:
                    call_observation.fail(exc)
                    raise

        try:
            client_call = await _retry_with_timeout(
                invoke_client,
                timeout_seconds=self.client_model.timeout_seconds,
                retries=self.client_model.max_retries,
            )
        except Exception as exc:  # noqa: BLE001 - provider implementations vary
            result = self._error_result(
                case,
                run_index,
                exc,
                latency=time.perf_counter() - started,
                usage=_merge_usage(usage),
                metadata={"client_attempts": call_attempts},
            )
            observation.finish(result)
            return result

        usage.append(client_call.usage)
        raw_response = _raw_for_evaluation(client_call)
        recording_provider = _RecordingProvider(
            self.judge_provider,
            observation,
            usage,
        )
        context = EvaluationContext(
            case=case,
            raw_response=raw_response,
            response=(
                client_call.content
                if isinstance(client_call.content, ClientResponse)
                else None
            ),
            provider=recording_provider,
            judge_model=self.judge_model,
            thresholds=self.thresholds,
            rules=self.rules,
            limits=self.limits,
            metadata={
                "client_model": client_call.model or self.client_model.name,
                "client_latency_seconds": client_call.latency_seconds,
                "client_attempts": call_attempts,
            },
        )

        evaluator_results: list[EvaluatorResult] = []
        critical_failed = False
        critical = [item for item in self.evaluators if item.critical]
        quality = [item for item in self.evaluators if not item.critical]

        for evaluator in critical:
            outcome = await _safe_evaluate(evaluator, context)
            evaluator_results.append(outcome)
            if not outcome.passed:
                critical_failed = True
                # Subsequent deterministic checks may require valid structure.
                if evaluator.name == "structure":
                    break

        if not critical_failed:
            for evaluator in quality:
                evaluator_results.append(await _safe_evaluate(evaluator, context))

        result = EvalResult(
            case_id=case.id,
            category=case.category,
            run_index=run_index,
            passed=bool(evaluator_results)
            and all(item.passed for item in evaluator_results),
            response=context.response,
            raw_response=_jsonable(raw_response),
            evaluator_results=evaluator_results,
            latency_seconds=time.perf_counter() - started,
            usage=_merge_usage(usage),
            metadata={
                "client_model": client_call.model or self.client_model.name,
                "judge_model": self.judge_model.name if self.judge_model else None,
                "client_attempts": call_attempts,
                "sales_message": case.message,
                "judges_skipped": critical_failed,
            },
        )
        observation.finish(result)
        return result

    @staticmethod
    def _error_result(
        case: EvalTestCase,
        run_index: int,
        error: BaseException,
        *,
        latency: float | None = None,
        usage: TokenUsage | None = None,
        metadata: dict[str, JsonValue] | None = None,
    ) -> EvalResult:
        return EvalResult(
            case_id=case.id,
            category=case.category,
            run_index=run_index,
            passed=False,
            latency_seconds=latency,
            usage=usage or TokenUsage(),
            error=f"{type(error).__name__}: {error}",
            metadata=metadata or {},
        )


class _RecordingProvider:
    """Decorate judge calls with retry, usage capture, and nested tracing."""

    def __init__(
        self,
        provider: LLMProvider,
        observation: CaseObservation,
        usage: list[TokenUsage],
    ) -> None:
        self.provider = provider
        self.observation = observation
        self.usage = usage

    async def invoke_client(
        self,
        *,
        system_prompt: str,
        persona: PersonaConfig,
        history: Sequence[ConversationMessage],
        message: str,
        model: ModelConfig,
    ) -> LLMCallResult:
        return await self.provider.invoke_client(
            system_prompt=system_prompt,
            persona=persona,
            history=history,
            message=message,
            model=model,
        )

    async def invoke_judge(
        self,
        *,
        prompt: str,
        evaluator_name: str,
        model: ModelConfig,
    ) -> LLMCallResult:
        attempt = 0

        async def invoke() -> LLMCallResult:
            nonlocal attempt
            attempt += 1
            with self.observation.model_call(
                name=f"eval-judge-{evaluator_name}",
                model=model,
                input_data={"prompt": prompt},
                metadata={"evaluator": evaluator_name, "attempt": attempt},
            ) as call_observation:
                try:
                    call = await self.provider.invoke_judge(
                        prompt=prompt,
                        evaluator_name=evaluator_name,
                        model=model,
                    )
                    normalized = _normalize_call_result(call)
                    call_observation.finish(normalized)
                    return normalized
                except BaseException as exc:
                    call_observation.fail(exc)
                    raise

        result = await _retry_with_timeout(
            invoke,
            timeout_seconds=model.timeout_seconds,
            retries=model.max_retries,
        )
        self.usage.append(result.usage)
        result.metadata.setdefault("attempts", attempt)
        return result


async def _safe_evaluate(
    evaluator: BaseEvaluator,
    context: EvaluationContext,
) -> EvaluatorResult:
    try:
        return await evaluator.evaluate(context)
    except Exception as exc:
        logger.exception("Evaluator %s failed for %s", evaluator.name, context.case.id)
        return EvaluatorResult(
            name=evaluator.name,
            passed=False,
            reason=f"Evaluator error: {type(exc).__name__}: {exc}",
            metadata={"error_type": type(exc).__name__},
        )


async def _retry_with_timeout(
    operation: Callable[[], Awaitable[T]],
    *,
    timeout_seconds: float,
    retries: int,
) -> T:
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(operation(), timeout=timeout_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider implementations vary
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(min(0.1 * (2**attempt), 1.0))
    assert last_error is not None
    if isinstance(last_error, asyncio.TimeoutError):
        raise ProviderError(
            f"provider timed out after {timeout_seconds:g} seconds "
            f"({retries + 1} attempts)"
        ) from last_error
    raise last_error


def _normalize_call_result(value: Any) -> LLMCallResult:
    if isinstance(value, LLMCallResult):
        return value
    if hasattr(value, "content"):
        return LLMCallResult(
            content=value.content,
            raw_content=getattr(value, "raw_content", None),
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


def _raw_for_evaluation(call: LLMCallResult) -> Any:
    # A provider-enforced structured model is stronger evidence than an empty
    # tool-call message body; plain providers/fakes still exercise raw JSON parsing.
    if isinstance(call.content, (ClientResponse, dict)):
        return call.content
    return call.raw_content if call.raw_content is not None else call.content


def _merge_usage(usages: Sequence[TokenUsage]) -> TokenUsage:
    return TokenUsage(
        input_tokens=_sum_known(item.input_tokens for item in usages),
        output_tokens=_sum_known(item.output_tokens for item in usages),
        total_tokens=_sum_known(item.total_tokens for item in usages),
        estimated_cost=_sum_known_float(item.estimated_cost for item in usages),
    )


def _sum_known(values) -> int | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _sum_known_float(values) -> float | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _jsonable(value: Any) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)


__all__ = ["EvalRunner", "default_evaluators"]

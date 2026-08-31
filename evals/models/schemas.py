"""Pydantic schemas shared by the evaluation framework."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    """Base for persisted/public data where unknown fields indicate a mistake."""

    model_config = ConfigDict(extra="forbid")


class ClientResponse(StrictModel):
    """Structured response produced by the simulated client."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reply: str = Field(min_length=1, description="Visible reply to the sales manager")
    intentions: str = Field(
        min_length=1,
        description="Internal client state, hidden from the sales manager",
    )
    done: bool = Field(description="Whether the conversation is complete")

    @field_validator("reply", "intentions")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class PersonaConfig(StrictModel):
    """Dataset-owned persona; the engine is intentionally persona-agnostic."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20_000)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("name", "description")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ConversationMessage(StrictModel):
    role: Literal["sales", "client"]
    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class EvalTestCase(StrictModel):
    """A single next-response evaluation with optional multi-turn history."""

    id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.-]+$")
    category: str = Field(min_length=1, max_length=100)
    persona: PersonaConfig
    history: list[ConversationMessage] = Field(default_factory=list, max_length=100)
    message: str = Field(min_length=1, max_length=20_000)
    expected_behavior: list[str] = Field(default_factory=list)
    forbidden_behavior: list[str] = Field(default_factory=list)
    expected_done: bool | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("category", "message")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("expected_behavior", "forbidden_behavior", "tags")
    @classmethod
    def reject_blank_list_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("list items must not be blank")
        return values


class ResponseLimits(StrictModel):
    reply_max_chars: int = Field(default=1_200, ge=1, le=100_000)
    intentions_max_chars: int = Field(default=2_000, ge=1, le=100_000)


class RuleConfig(StrictModel):
    """Literal checks only; semantic behaviors belong to LLM judges."""

    forbidden_phrases: list[str] = Field(default_factory=list)
    system_leakage_phrases: list[str] = Field(
        default_factory=lambda: [
            "system prompt",
            "system message",
            "developer message",
            "скрытые инструкции",
            "системный промпт",
        ]
    )
    role_break_phrases: list[str] = Field(
        default_factory=lambda: [
            "as an ai",
            "as a language model",
            "я языковая модель",
            "я искусственный интеллект",
            "не могу продолжать роль",
        ]
    )
    reject_markdown_code_fences: bool = True
    case_sensitive: bool = False


class EvaluatorThresholds(StrictModel):
    persona: float = Field(default=4.0, ge=1, le=5)
    realism: float = Field(default=4.0, ge=1, le=5)
    consistency: float = Field(default=4.0, ge=1, le=5)
    intentions: float = Field(default=2.0, ge=0, le=3)
    conversation: float = Field(default=4.0, ge=1, le=5)


class ModelConfig(StrictModel):
    """Provider-neutral model invocation settings."""

    name: str = Field(min_length=1)
    provider: str = Field(default="openai_compatible", min_length=1)
    base_url: str | None = None
    api_key: SecretStr | None = Field(default=None, exclude=True)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    temperature: float = Field(default=0.0, ge=0, le=2)
    timeout_seconds: float = Field(default=60.0, gt=0, le=3_600)
    max_retries: int = Field(default=2, ge=0, le=20)
    seed: int | None = None


class TokenUsage(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def fill_total(self) -> TokenUsage:
        if (
            self.total_tokens is None
            and self.input_tokens is not None
            and self.output_tokens is not None
        ):
            self.total_tokens = self.input_tokens + self.output_tokens
        return self


class LLMCallResult(BaseModel):
    """Normalized provider result. ``content`` may already be a Pydantic model."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    content: Any
    raw_content: JsonValue | None = None
    model: str | None = None
    latency_seconds: float | None = Field(default=None, ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class JudgeResult(StrictModel):
    score: float = Field(ge=0, le=5)
    passed: bool
    reason: str = Field(min_length=1, max_length=4_000)
    violations: list[str] = Field(default_factory=list)


class EvaluatorResult(StrictModel):
    name: str = Field(min_length=1)
    score: float | None = None
    passed: bool
    reason: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class EvalResult(StrictModel):
    case_id: str
    category: str
    run_index: int = Field(ge=1)
    passed: bool
    response: ClientResponse | None = None
    raw_response: JsonValue | None = None
    evaluator_results: list[EvaluatorResult] = Field(default_factory=list)
    latency_seconds: float | None = Field(default=None, ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    error: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class MetricStats(StrictModel):
    count: int = Field(ge=0)
    mean: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    std_dev: float | None = Field(default=None, ge=0)
    pass_rate: float = Field(ge=0, le=1)


class EvalRun(StrictModel):
    run_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    client_model: str
    judge_model: str | None = None
    prompt_version: str
    judge_prompt_version: str
    dataset: str
    dataset_version: str
    runs_per_case: int = Field(ge=1)
    results: list[EvalResult] = Field(default_factory=list)
    evaluator_stats: dict[str, MetricStats] = Field(default_factory=dict)
    overall_pass_rate: float = Field(default=0, ge=0, le=1)
    total_latency_seconds: float = Field(default=0, ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ComparisonMetric(StrictModel):
    name: str
    old: float | None = None
    new: float | None = None
    delta: float | None = None
    unit: Literal["rate", "score", "seconds", "tokens", "cost"]
    regression: bool = False


class RunComparison(StrictModel):
    old_run_id: str
    new_run_id: str
    metrics: list[ComparisonMetric] = Field(default_factory=list)
    regressions: list[str] = Field(default_factory=list)
    has_quality_regression: bool = False


def validate_client_response(
    value: str | bytes | bytearray | dict[str, Any] | ClientResponse,
    limits: ResponseLimits | None = None,
) -> ClientResponse:
    """Strictly parse a response and apply configurable length limits."""
    if isinstance(value, ClientResponse):
        response = value
    elif isinstance(value, (str, bytes, bytearray)):
        response = ClientResponse.model_validate_json(value)
    else:
        response = ClientResponse.model_validate(value)

    configured_limits = limits or ResponseLimits()
    if len(response.reply) > configured_limits.reply_max_chars:
        raise ValueError(
            f"reply exceeds {configured_limits.reply_max_chars} characters"
        )
    if len(response.intentions) > configured_limits.intentions_max_chars:
        raise ValueError(
            f"intentions exceeds {configured_limits.intentions_max_chars} characters"
        )
    return response


def load_eval_run(path: str | Path) -> EvalRun:
    return EvalRun.model_validate_json(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "ClientResponse",
    "ComparisonMetric",
    "ConversationMessage",
    "EvalResult",
    "EvalRun",
    "EvalTestCase",
    "EvaluatorResult",
    "EvaluatorThresholds",
    "JsonValue",
    "JudgeResult",
    "LLMCallResult",
    "MetricStats",
    "ModelConfig",
    "PersonaConfig",
    "ResponseLimits",
    "RuleConfig",
    "RunComparison",
    "TokenUsage",
    "load_eval_run",
    "validate_client_response",
]

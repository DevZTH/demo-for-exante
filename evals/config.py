"""Environment-backed configuration kept outside evaluation business logic."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from evals.models.schemas import (
    EvaluatorThresholds,
    ModelConfig,
    ResponseLimits,
    RuleConfig,
)
from evals.prompts.judge import JUDGE_PROMPT_VERSION

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class EvalSettings(BaseSettings):
    client_model: str = Field(
        default="gemma4:12b",
        validation_alias=AliasChoices(
            "EVAL_CLIENT_MODEL", "CLIENT_MODEL", "CHAT_LLM_MODEL"
        ),
    )
    judge_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EVAL_JUDGE_MODEL", "JUDGE_MODEL"),
    )
    client_base_url: str | None = Field(
        default="http://localhost:11434/v1",
        validation_alias=AliasChoices(
            "EVAL_CLIENT_BASE_URL", "CLIENT_BASE_URL", "CHAT_LLM_BASE_URL"
        ),
    )
    judge_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EVAL_JUDGE_BASE_URL", "JUDGE_BASE_URL"),
    )
    client_api_key: SecretStr | None = Field(
        default=SecretStr("ollama"),
        validation_alias=AliasChoices(
            "EVAL_CLIENT_API_KEY",
            "CLIENT_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "CHAT_LLM_API_KEY",
        ),
    )
    judge_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "EVAL_JUDGE_API_KEY",
            "JUDGE_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
        ),
    )
    client_extra_headers: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices(
            "EVAL_CLIENT_EXTRA_HEADERS", "CHAT_LLM_EXTRA_HEADERS"
        ),
    )
    judge_extra_headers: dict[str, str] = Field(default_factory=dict)
    client_temperature: float = Field(default=0.2, ge=0, le=2)
    judge_temperature: float = Field(default=0.0, ge=0, le=2)
    timeout_seconds: float = Field(default=60.0, gt=0, le=3_600)
    retries: int = Field(default=2, ge=0, le=20)
    concurrency: int = Field(default=5, ge=1, le=100)
    seed: int | None = None

    reply_max_chars: int = Field(default=1_200, ge=1)
    intentions_max_chars: int = Field(default=2_000, ge=1)
    forbidden_phrases: list[str] = Field(default_factory=list)
    persona_threshold: float = Field(default=4.0, ge=1, le=5)
    realism_threshold: float = Field(default=4.0, ge=1, le=5)
    consistency_threshold: float = Field(default=4.0, ge=1, le=5)
    intentions_threshold: float = Field(default=2.0, ge=0, le=3)
    conversation_threshold: float = Field(default=4.0, ge=1, le=5)

    prompt_version: str = "local"
    judge_prompt_version: str = JUDGE_PROMPT_VERSION
    dataset_version: str = "1.0"
    system_prompt_path: Path = PROJECT_ROOT / "backend" / "agent" / "customer.md"
    datasets_dir: Path = Path(__file__).resolve().parent / "datasets"
    output_dir: Path = PROJECT_ROOT / "eval_results"
    langfuse_enabled: bool = True
    quality_regression_threshold: float = Field(default=0.05, ge=0)
    score_regression_threshold: float = Field(default=0.25, ge=0)
    latency_regression_threshold_percent: float = Field(default=15.0, ge=0)

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / "backend" / ".env",
        env_prefix="EVAL_",
        extra="ignore",
    )

    def client_config(self) -> ModelConfig:
        return ModelConfig(
            name=self.client_model,
            base_url=self.client_base_url,
            api_key=self.client_api_key,
            extra_headers=self.client_extra_headers,
            temperature=self.client_temperature,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.retries,
            seed=self.seed,
        )

    def judge_config(self) -> ModelConfig:
        return ModelConfig(
            name=self.judge_model or self.client_model,
            base_url=self.judge_base_url or self.client_base_url,
            api_key=self.judge_api_key or self.client_api_key,
            extra_headers=self.judge_extra_headers or self.client_extra_headers,
            temperature=self.judge_temperature,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.retries,
            seed=self.seed,
        )

    def response_limits(self) -> ResponseLimits:
        return ResponseLimits(
            reply_max_chars=self.reply_max_chars,
            intentions_max_chars=self.intentions_max_chars,
        )

    def rule_config(self) -> RuleConfig:
        return RuleConfig(forbidden_phrases=self.forbidden_phrases)

    def thresholds(self) -> EvaluatorThresholds:
        return EvaluatorThresholds(
            persona=self.persona_threshold,
            realism=self.realism_threshold,
            consistency=self.consistency_threshold,
            intentions=self.intentions_threshold,
            conversation=self.conversation_threshold,
        )

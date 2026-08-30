from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    app_name: str = "EXANTE Scenario Trainer"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    sqlite_path: Path = BASE_DIR / "data" / "chat.sqlite3"
    chat_storage_mode: Literal["sqlite", "sqlite_vec"] = "sqlite_vec"
    history_window_messages: int = Field(default=16, ge=0, le=100)
    semantic_memory_limit: int = Field(default=6, ge=0, le=20)
    embedding_dimensions: int = Field(default=64, ge=16, le=1536)

    llm_provider: Literal["ollama", "openrouter", "openai_compatible"] = "ollama"
    llm_model: str = "gemma4:12b"
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_timeout_seconds: float = Field(default=60, gt=0)

    ollama_base_url: str = "http://localhost:11434"

    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_url: str | None = None
    openrouter_app_title: str | None = None

    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_prefix="CHAT_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

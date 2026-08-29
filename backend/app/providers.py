from __future__ import annotations

import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_openrouter import ChatOpenRouter

from backend.settings import Settings


def build_chat_model(settings: Settings) -> BaseChatModel:
    if settings.llm_provider == "ollama":
        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=settings.llm_temperature,
        )

    if settings.llm_provider == "openrouter":
        api_key = _secret_value(settings.openrouter_api_key) or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "CHAT_OPENROUTER_API_KEY or OPENROUTER_API_KEY is required for OpenRouter"
            )

        return ChatOpenRouter(
            model=settings.llm_model,
            api_key=api_key,
            base_url=settings.openrouter_base_url,
            app_url=settings.openrouter_app_url,
            app_title=settings.openrouter_app_title,
            temperature=settings.llm_temperature,
            timeout=int(settings.llm_timeout_seconds * 1000),
        )

    if settings.llm_provider == "openai_compatible":
        api_key = _secret_value(settings.openai_api_key) or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("CHAT_OPENAI_API_KEY or OPENAI_API_KEY is required")

        return ChatOpenAI(
            model=settings.llm_model,
            api_key=api_key,
            base_url=settings.openai_base_url,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
        )

    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


def _secret_value(value: object) -> str | None:
    if value is None:
        return None
    get_secret_value = getattr(value, "get_secret_value", None)
    if callable(get_secret_value):
        return get_secret_value()
    return str(value)

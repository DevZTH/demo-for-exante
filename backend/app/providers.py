from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from backend.settings import Settings


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Build the sole OpenAI-compatible chat client used by the application."""
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=_secret_value(settings.llm_api_key),
        base_url=settings.llm_base_url,
        default_headers=settings.llm_extra_headers,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
    )


def _secret_value(value: object) -> str | None:
    if value is None:
        return None
    get_secret_value = getattr(value, "get_secret_value", None)
    if callable(get_secret_value):
        return get_secret_value()
    return str(value)

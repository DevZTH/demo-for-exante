from __future__ import annotations

import os
import re
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.chat_models import SimpleChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_openrouter import ChatOpenRouter

from backend.settings import Settings


def build_chat_model(settings: Settings) -> BaseChatModel:
    if settings.llm_provider == "demo":
        return DemoChatModel()

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


class DemoChatModel(SimpleChatModel):
    """Small local LangChain chat model for offline project demos."""

    @property
    def _llm_type(self) -> str:
        return "local-demo-chat"

    def _call(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> str:
        human_messages = [
            str(message.content).strip()
            for message in messages
            if isinstance(message, HumanMessage) and str(message.content).strip()
        ]
        current = human_messages[-1] if human_messages else ""
        previous = human_messages[:-1]
        facts = _extract_facts(previous)

        if _is_memory_question(current):
            if facts:
                return "Я помню из этого диалога: " + "; ".join(facts) + "."
            if previous:
                return "Я помню предыдущие сообщения: " + "; ".join(previous[-3:]) + "."
            return "Пока в этом диалоге нет сохраненных фактов, но новые сообщения будут сохранены в памяти."

        asks_name = _asks_name(current)
        asks_project = _asks_project(current)
        if asks_name or asks_project:
            name = _latest_name(facts)
            project_fact = _latest_project_fact(facts)
            answer_parts: list[str] = []

            if asks_name:
                if name:
                    answer_parts.append(f"Вас зовут {name}.")
                else:
                    answer_parts.append("Вы пока не называли имя в этом диалоге.")

            if asks_project:
                if project_fact:
                    answer_parts.append(f"Судя по памяти диалога, {project_fact}.")
                else:
                    answer_parts.append("В памяти диалога пока нет описания проекта.")

            return " ".join(answer_parts)

        if "запомни" in current.lower():
            remembered = _clean_fact(current)
            return f"Запомнил: {remembered}."

        memory_note = ""
        if facts:
            memory_note = f"\n\nИз памяти я также учитываю: {'; '.join(facts[-3:])}."

        return (
            f"Вы написали: {current}\n\n"
            "Я локальный demo-бот LangChain. Могу поддерживать диалог, а историю и факты "
            f"этого чата backend сохраняет в SQLite-памяти.{memory_note}"
        )


def _extract_facts(messages: list[str]) -> list[str]:
    facts: list[str] = []

    for message in messages:
        cleaned = _clean_fact(message)
        lowered = message.lower()

        added_structured_fact = False
        name_match = re.search(r"меня зовут\s+([^.,!?;\n]+)", message, flags=re.IGNORECASE)
        if name_match:
            name = re.split(r"\s+(?:и|а|но)\s+", name_match.group(1).strip(), maxsplit=1)[0]
            facts.append(f"вас зовут {name.strip()}")
            added_structured_fact = True

        project_match = re.search(
            r"(?:мой|наш)\s+проект\s+(?:про|о|об)\s+([^.!?\n]+)",
            message,
            flags=re.IGNORECASE,
        )
        if project_match:
            facts.append(f"проект про {project_match.group(1).strip()}")
            added_structured_fact = True

        if "запомни" in lowered and not added_structured_fact:
            facts.append(cleaned)

    return facts[-6:]


def _clean_fact(message: str) -> str:
    text = " ".join(message.split()).strip()
    text = re.sub(r"^запомни[:,]?\s*(что\s*)?", "", text, flags=re.IGNORECASE)
    return text.rstrip(".")


def _is_memory_question(message: str) -> bool:
    lowered = message.lower()
    return any(
        phrase in lowered
        for phrase in (
            "что ты помнишь",
            "что помнишь",
            "помнишь",
            "что я говорил",
            "что я сказал",
        )
    )


def _asks_name(message: str) -> bool:
    lowered = message.lower()
    return "как меня зовут" in lowered or "мое имя" in lowered or "моё имя" in lowered


def _asks_project(message: str) -> bool:
    lowered = message.lower()
    return "о чем мой проект" in lowered or "про что мой проект" in lowered


def _latest_name(facts: list[str]) -> str | None:
    for fact in reversed(facts):
        if fact.startswith("вас зовут "):
            return fact.removeprefix("вас зовут ").strip()
    return None


def _latest_project_fact(facts: list[str]) -> str | None:
    for fact in reversed(facts):
        if fact.startswith("проект "):
            return fact.strip()
    return None

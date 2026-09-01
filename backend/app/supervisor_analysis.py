"""Dependency-free supervisor analysis helpers shared by the API and CLI."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from backend.app.domain import MessageRecord, assistant_reply_or_fallback
from backend.app.schemas import AgentResponseData, SupervisorAnalysisData
from backend.app.storage import ChatRepository
from backend.app.supervisor_contract import (
    INITIAL_SUPERVISOR_ANALYSIS_CONTRACT,
    RETRY_SUPERVISOR_ANALYSIS_CONTRACT,
    validate_supervisor_report_language,
)


def format_history_for_analysis(history: Sequence[object]) -> str:
    """Render message-like objects as an explicit supervisor transcript."""
    transcript: list[str] = []
    for number, item in enumerate(history, start=1):
        speaker = "rm" if getattr(item, "type", "") in {"human", "user"} else "client"
        raw_content = getattr(item, "content", item)
        content = raw_content if isinstance(raw_content, str) else str(raw_content)
        transcript.append(f"{number}. [{speaker}]\n{content}")
    return "\n\n".join(transcript)


def format_persisted_history(messages: Sequence[MessageRecord]) -> str:
    """Render persisted user and assistant messages for the supervisor."""
    transcript: list[str] = []
    for number, message in enumerate(messages, start=1):
        speaker = "rm" if message.role == "user" else "client"
        transcript.append(f"{number}. [{speaker}]\n{_visible_content(message)}")
    return "\n\n".join(transcript)


async def analyze_history(
    *,
    history: Sequence[object],
    supervisor_chain: object,
    supervisor_prompt: str,
    customer_profile: str,
) -> SupervisorAnalysisData:
    """Ask the supervisor to analyse an in-memory CLI conversation."""
    request = {
        "supervisor_prompt": supervisor_prompt,
        "customer_profile": customer_profile,
        "conversation": format_history_for_analysis(history),
    }
    contracts = (
        INITIAL_SUPERVISOR_ANALYSIS_CONTRACT,
        RETRY_SUPERVISOR_ANALYSIS_CONTRACT,
    )
    for contract in contracts:
        result = await supervisor_chain.ainvoke({**request, "analysis_contract": contract})
        try:
            analysis = _coerce_analysis(result)
            validate_history_analysis(analysis, history)
            validate_supervisor_report_language(analysis)
            return analysis
        except ValueError:
            if contract == contracts[-1]:
                raise

    raise RuntimeError("Не удалось сформировать отчёт супервайзера")


async def analyze_persisted_scenario(
    *,
    scenario_id: str,
    repository: ChatRepository,
    supervisor_chain: object,
    get_supervisor_prompt: Callable[[], str],
    get_customer_profile: Callable[[], str],
) -> SupervisorAnalysisData:
    """Ask the supervisor to analyse all visible messages in one scenario."""
    repository.require_scenario(scenario_id)
    messages = [
        message
        for message in repository.list_messages(scenario_id)
        if message.role in {"user", "assistant"}
    ]
    if not messages:
        raise ValueError("Невозможно проанализировать сценарий без реплик.")

    request = {
        "supervisor_prompt": get_supervisor_prompt(),
        "customer_profile": get_customer_profile(),
        "conversation": format_persisted_history(messages),
    }
    contracts = (
        INITIAL_SUPERVISOR_ANALYSIS_CONTRACT,
        RETRY_SUPERVISOR_ANALYSIS_CONTRACT,
    )
    for contract in contracts:
        result = await supervisor_chain.ainvoke(
            {**request, "analysis_contract": contract},
            config={"run_name": "analyze-scenario"},
        )
        try:
            analysis = _coerce_analysis(result)
            validate_persisted_analysis(analysis, messages)
            validate_supervisor_report_language(analysis)
            return analysis
        except ValueError:
            if contract == contracts[-1]:
                raise

    raise RuntimeError("Не удалось сформировать отчёт супервайзера")


def validate_history_analysis(
    analysis: SupervisorAnalysisData,
    history: Sequence[object],
) -> None:
    expected = [
        (number, "rm" if getattr(message, "type", "") in {"human", "user"} else "client")
        for number, message in enumerate(history, start=1)
    ]
    _validate_message_order(analysis, expected)


def validate_persisted_analysis(
    analysis: SupervisorAnalysisData,
    messages: Sequence[MessageRecord],
) -> None:
    expected = [
        (number, "rm" if message.role == "user" else "client")
        for number, message in enumerate(messages, start=1)
    ]
    _validate_message_order(analysis, expected)


def print_supervisor_analysis(analysis: SupervisorAnalysisData) -> None:
    """Render structured supervisor output for the terminal."""
    print("\nРазбор супервайзера")
    print(f"Итоговая оценка RM: {analysis.overall_score}/100")
    print(f"Итог: {analysis.overall_assessment}")
    print("\nРазбор реплик:")
    for item in analysis.message_analyses:
        speaker = "RM" if item.speaker == "rm" else "Клиент"
        score_label = "Оценка" if item.speaker == "rm" else "Сигнал"
        print(f"{item.message_number}. {speaker} — {score_label}: {item.score}/10")
        print(f"   Разбор: {item.assessment}")
        print(f"   Рекомендация: {item.recommendation}")

    print("\nПриоритетные рекомендации:")
    for number, recommendation in enumerate(analysis.priority_recommendations, start=1):
        print(f"{number}. {recommendation}")


def _coerce_analysis(result: object) -> SupervisorAnalysisData:
    return result if isinstance(result, SupervisorAnalysisData) else SupervisorAnalysisData.model_validate(result)


def _validate_message_order(
    analysis: SupervisorAnalysisData,
    expected: list[tuple[int, str]],
) -> None:
    actual = [(item.message_number, item.speaker) for item in analysis.message_analyses]
    if actual != expected:
        raise ValueError("супервайзер должен разобрать каждую реплику в исходном порядке")


def _visible_content(message: MessageRecord) -> str:
    if message.role != "assistant":
        return message.content

    return assistant_reply_or_fallback(
        message.content,
        fallback="Ответ клиента из предыдущего сообщения недоступен.",
        parser=AgentResponseData.model_validate_json,
    )


__all__ = [
    "analyze_history",
    "analyze_persisted_scenario",
    "format_history_for_analysis",
    "format_persisted_history",
    "print_supervisor_analysis",
    "validate_history_analysis",
    "validate_persisted_analysis",
]

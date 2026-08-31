"""Interactive EXANTE scenario chat that calls LangChain directly.

Run with: python -m backend.cli
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from typing import Sequence

# Support both `python -m backend.cli` from the repository root and
# `python -m cli` when the current directory is `backend/`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from backend.app.providers import build_chat_model
from backend.app.schemas import AgentResponseData, SupervisorAnalysisData
from backend.settings import Settings, get_settings


CUSTOMER_PROMPT_PATH = Path(__file__).resolve().parent / "agent" / "customer.md"
SUPERVISOR_PROMPT_PATH = Path(__file__).resolve().parent / "agent" / "supervisor.md"
EXIT_COMMANDS = {"/exit", "/quit", "/q"}


def build_chain(settings: Settings):
    """Create the LangChain prompt/model pipeline without FastAPI or storage."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "{system_prompt}"),
            MessagesPlaceholder("history"),
            ("human", "{input}"),
        ]
    )
    return prompt | build_chat_model(settings).with_structured_output(AgentResponseData)


def build_supervisor_chain(settings: Settings):
    """Create the independent supervisor chain used by the /analyze command."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "{supervisor_prompt}"),
            ("system", "<customer_profile>\n{customer_profile}\n</customer_profile>"),
            ("human", "<conversation>\n{conversation}\n</conversation>"),
        ]
    )
    return prompt | build_chat_model(settings).with_structured_output(SupervisorAnalysisData)


def read_system_prompt() -> str:
    """Load the customer persona used by both the API and CLI clients."""
    return CUSTOMER_PROMPT_PATH.read_text(encoding="utf-8")


def read_supervisor_prompt() -> str:
    """Load the coaching rules for the supervisor role."""
    return SUPERVISOR_PROMPT_PATH.read_text(encoding="utf-8")


def format_history_for_analysis(history: Sequence[BaseMessage]) -> str:
    """Make every spoken message explicit for a whole-conversation review."""
    transcript: list[str] = []
    for number, item in enumerate(history, start=1):
        speaker = "rm" if isinstance(item, HumanMessage) else "client"
        content = item.content if isinstance(item.content, str) else str(item.content)
        transcript.append(f"{number}. [{speaker}]\n{content}")
    return "\n\n".join(transcript)


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


async def analyze_history(
    *,
    history: Sequence[BaseMessage],
    supervisor_chain: object,
    supervisor_prompt: str,
    customer_profile: str,
) -> SupervisorAnalysisData:
    """Ask the supervisor to analyse all messages collected in this CLI session."""
    invoke = getattr(supervisor_chain, "ainvoke")
    result = await invoke(
        {
            "supervisor_prompt": supervisor_prompt,
            "customer_profile": customer_profile,
            "conversation": format_history_for_analysis(history),
        }
    )
    analysis = (
        result
        if isinstance(result, SupervisorAnalysisData)
        else SupervisorAnalysisData.model_validate(result)
    )
    _validate_message_analyses(analysis, history)
    return analysis


def _validate_message_analyses(
    analysis: SupervisorAnalysisData,
    history: Sequence[BaseMessage],
) -> None:
    """Require the model to honour the per-message analysis contract."""
    expected = [
        (number, "rm" if isinstance(message, HumanMessage) else "client")
        for number, message in enumerate(history, start=1)
    ]
    actual = [
        (item.message_number, item.speaker)
        for item in analysis.message_analyses
    ]
    if actual != expected:
        raise ValueError(
            "супервайзер должен разобрать каждую реплику в исходном порядке"
        )


async def run_chat(*, show_signal: bool) -> None:
    settings = get_settings()
    chain = build_chain(settings)
    supervisor_chain = build_supervisor_chain(settings)
    system_prompt = read_system_prompt()
    supervisor_prompt = read_supervisor_prompt()
    history: list[BaseMessage] = []

    print(f"EXANTE Scenario Trainer · {settings.llm_model} @ {settings.llm_base_url}")
    print("Введите реплику Relationship Manager. Команды: /analyze, /reset, /quit")

    while True:
        try:
            message = input("\nRM > ").strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print("\nДиалог завершён.")
            break

        if not message:
            continue
        if message.lower() in EXIT_COMMANDS:
            break
        if message.lower() == "/reset":
            history.clear()
            print("История диалога очищена.")
            continue
        if message.lower() == "/analyze":
            if not history:
                print("Нет реплик для анализа. Начните диалог и повторите /analyze.")
                continue
            try:
                analysis = await analyze_history(
                    history=history,
                    supervisor_chain=supervisor_chain,
                    supervisor_prompt=supervisor_prompt,
                    customer_profile=system_prompt,
                )
            except Exception as exc:
                print(f"Не удалось получить анализ супервайзера: {exc}")
                continue
            print_supervisor_analysis(analysis)
            continue

        try:
            result = await chain.ainvoke(
                {
                    "system_prompt": system_prompt,
                    "history": history,
                    "input": message,
                }
            )
            response = (
                result
                if isinstance(result, AgentResponseData)
                else AgentResponseData.model_validate(result)
            )
        except Exception as exc:
            print(f"Не удалось получить ответ модели: {exc}")
            continue

        # Keep only the spoken customer reply in the conversation context.
        history.extend([HumanMessage(content=message), AIMessage(content=response.reply)])
        print(f"\nКлиент > {response.reply}")

        if show_signal:
            print(
                "  Сигнал: "
                f"state={response.state}, trust={response.trust}, "
                f"purchase_probability={response.purchase_probability}, done={response.done}"
            )

        if response.done:
            print("Сценарий завершён. Используйте /reset, чтобы начать новый.")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EXANTE scenario chat, directly through LangChain (no FastAPI)."
    )
    parser.add_argument(
        "--show-signal",
        action="store_true",
        help="показывать state, trust, purchase_probability и done после реплики",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(run_chat(show_signal=args.show_signal))


if __name__ == "__main__":
    main()

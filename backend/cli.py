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
from backend.app.schemas import AgentResponseData
from backend.settings import Settings, get_settings


PROMPT_PATH = Path(__file__).resolve().parent / "agent" / "customer.md"
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


def read_system_prompt() -> str:
    """Load the customer persona used by both the API and CLI clients."""
    return PROMPT_PATH.read_text(encoding="utf-8")


async def run_chat(*, show_signal: bool) -> None:
    settings = get_settings()
    chain = build_chain(settings)
    system_prompt = read_system_prompt()
    history: list[BaseMessage] = []

    print(f"EXANTE Scenario Trainer · {settings.llm_model} @ {settings.llm_base_url}")
    print("Введите реплику Relationship Manager. Команды: /reset, /quit")

    while True:
        try:
            message = input("RM > ").strip()
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
        print(f"Клиент > {response.reply}")

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

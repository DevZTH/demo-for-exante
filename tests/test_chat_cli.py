from __future__ import annotations

import asyncio
from dataclasses import dataclass

from backend.app import supervisor_analysis as supervisor
from backend.app.schemas import SupervisorAnalysisData
from backend.app.supervisor_contract import RETRY_SUPERVISOR_ANALYSIS_CONTRACT


@dataclass(frozen=True)
class ChatMessage:
    content: str
    type: str


def human_message(content: str) -> ChatMessage:
    return ChatMessage(content=content, type="human")


def ai_message(content: str) -> ChatMessage:
    return ChatMessage(content=content, type="ai")


class StubChain:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def ainvoke(self, values: dict[str, object]) -> object:
        self.calls.append(values)
        return self.result


def supervisor_analysis() -> SupervisorAnalysisData:
    return SupervisorAnalysisData.model_validate(
        {
            "overall_score": 82,
            "overall_assessment": "RM начал discovery и получил полезный сигнал.",
            "message_analyses": [
                {
                    "message_number": 1,
                    "speaker": "rm",
                    "score": 8,
                    "assessment": "Открытый вопрос помогает понять текущую ситуацию.",
                    "recommendation": "Уточнить, что не устраивает у текущего брокера.",
                },
                {
                    "message_number": 2,
                    "speaker": "client",
                    "score": 5,
                    "assessment": "Клиент проявляет интерес, но пока не видит причины менять брокера.",
                    "recommendation": "Связать следующий вопрос с его текущим опытом.",
                },
            ],
            "priority_recommendations": [
                "Продолжить discovery до презентации продукта.",
            ],
        }
    )


def test_format_history_for_analysis_preserves_every_message() -> None:
    transcript = supervisor.format_history_for_analysis(
        [
            human_message("Что важно в текущем брокере?"),
            ai_message("Мне нравятся низкие комиссии."),
        ]
    )

    assert transcript == (
        "1. [rm]\nЧто важно в текущем брокере?\n\n"
        "2. [client]\nМне нравятся низкие комиссии."
    )


def test_analyze_history_sends_full_transcript_to_supervisor() -> None:
    chain = StubChain(supervisor_analysis())
    history = [human_message("Здравствуйте"), ai_message("Добрый день")]

    result = asyncio.run(
        supervisor.analyze_history(
            history=history,
            supervisor_chain=chain,
            supervisor_prompt="supervisor rules",
            customer_profile="customer profile",
        )
    )

    assert result.overall_score == 82
    assert chain.calls[0]["conversation"] == "1. [rm]\nЗдравствуйте\n\n2. [client]\nДобрый день"
    assert "КАЖДОЙ строки" in chain.calls[0]["analysis_contract"]


def test_analyze_history_rejects_incomplete_message_review() -> None:
    chain = StubChain(
        supervisor_analysis().model_copy(
            update={"message_analyses": [supervisor_analysis().message_analyses[0]]}
        )
    )

    try:
        asyncio.run(
            supervisor.analyze_history(
                history=[human_message("Здравствуйте"), ai_message("Добрый день")],
                supervisor_chain=chain,
                supervisor_prompt="supervisor rules",
                customer_profile="customer profile",
            )
        )
    except ValueError as error:
        assert "каждую реплику" in str(error)
    else:
        raise AssertionError("Incomplete supervisor analysis must be rejected")

    assert len(chain.calls) == 2
    assert chain.calls[1]["analysis_contract"] == RETRY_SUPERVISOR_ANALYSIS_CONTRACT


def test_print_supervisor_analysis(capsys) -> None:
    supervisor.print_supervisor_analysis(supervisor_analysis())

    output = capsys.readouterr().out
    assert "Итоговая оценка RM: 82/100" in output
    assert "1. RM — Оценка: 8/10" in output
    assert "2. Клиент — Сигнал: 5/10" in output

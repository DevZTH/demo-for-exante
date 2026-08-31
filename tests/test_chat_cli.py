from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from backend import cli
from backend.app.schemas import AgentResponseData, SupervisorAnalysisData


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
    transcript = cli.format_history_for_analysis(
        [
            HumanMessage(content="Что важно в текущем брокере?"),
            AIMessage(content="Мне нравятся низкие комиссии."),
        ]
    )

    assert transcript == (
        "1. [rm]\nЧто важно в текущем брокере?\n\n"
        "2. [client]\nМне нравятся низкие комиссии."
    )


def test_analyze_history_sends_full_transcript_to_supervisor() -> None:
    chain = StubChain(supervisor_analysis())
    history = [HumanMessage(content="Здравствуйте"), AIMessage(content="Добрый день")]

    result = asyncio.run(
        cli.analyze_history(
            history=history,
            supervisor_chain=chain,
            supervisor_prompt="supervisor rules",
            customer_profile="customer profile",
        )
    )

    assert result.overall_score == 82
    assert chain.calls[0]["conversation"] == "1. [rm]\nЗдравствуйте\n\n2. [client]\nДобрый день"


def test_analyze_history_rejects_incomplete_message_review() -> None:
    chain = StubChain(
        supervisor_analysis().model_copy(
            update={"message_analyses": [supervisor_analysis().message_analyses[0]]}
        )
    )

    try:
        asyncio.run(
            cli.analyze_history(
                history=[HumanMessage(content="Здравствуйте"), AIMessage(content="Добрый день")],
                supervisor_chain=chain,
                supervisor_prompt="supervisor rules",
                customer_profile="customer profile",
            )
        )
    except ValueError as error:
        assert "каждую реплику" in str(error)
    else:
        raise AssertionError("Incomplete supervisor analysis must be rejected")


def test_analyze_command_prints_supervisor_report(monkeypatch, capsys) -> None:
    customer_chain = StubChain(
        AgentResponseData(
            reply="Мне интересны комиссии.",
            intetions="Я осторожно изучаю варианты.",
            state="curious",
            trust=50,
            purchase_probability=30,
            done=False,
        )
    )
    analysis_chain = StubChain(supervisor_analysis())
    commands = iter(["Здравствуйте", "/analyze", "/quit"])

    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(
        llm_model="test-model", llm_base_url="http://test"
    ))
    monkeypatch.setattr(cli, "build_chain", lambda _settings: customer_chain)
    monkeypatch.setattr(cli, "build_supervisor_chain", lambda _settings: analysis_chain)
    monkeypatch.setattr(cli, "read_system_prompt", lambda: "customer profile")
    monkeypatch.setattr(cli, "read_supervisor_prompt", lambda: "supervisor rules")
    monkeypatch.setattr("builtins.input", lambda _prompt: next(commands))

    asyncio.run(cli.run_chat(show_signal=False))

    output = capsys.readouterr().out
    assert "Итоговая оценка RM: 82/100" in output
    assert "1. RM — Оценка: 8/10" in output
    assert "2. Клиент — Сигнал: 5/10" in output
    assert analysis_chain.calls[0]["conversation"] == (
        "1. [rm]\nЗдравствуйте\n\n2. [client]\nМне интересны комиссии."
    )

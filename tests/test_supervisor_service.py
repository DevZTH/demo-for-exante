from __future__ import annotations

import asyncio

import pytest

from backend.app.api_errors import supervisor_analysis_error
from backend.app.schemas import AgentResponseData, SupervisorAnalysisData
from backend.app.storage import ChatRepository, ScenarioNotFoundError
from backend.app.supervisor_analysis import analyze_persisted_scenario
from backend.app.supervisor_contract import RETRY_SUPERVISOR_ANALYSIS_CONTRACT
from backend.settings import Settings


class StubSupervisorChain:
    def __init__(self, result: SupervisorAnalysisData) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def ainvoke(self, values: dict[str, object], **_: object) -> SupervisorAnalysisData:
        self.calls.append(values)
        return self.result


def analysis() -> SupervisorAnalysisData:
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
            "priority_recommendations": ["Продолжить discovery до презентации продукта."],
        }
    )


def make_analysis_request(tmp_path, chain: StubSupervisorChain):
    settings = Settings(
        sqlite_path=tmp_path / "scenario.sqlite3",
        chat_storage_mode="sqlite",
    )
    repository = ChatRepository(settings)
    repository.init_db()
    scenario = repository.create_scenario(title="Supervisor test")
    repository.add_message(scenario.id, "user", "Что важно в текущем брокере?")
    repository.add_message(
        scenario.id,
        "assistant",
        AgentResponseData(
            reply="Мне нравятся низкие комиссии.",
            intetions="Я осторожно изучаю варианты.",
            state="curious",
            trust=50,
            purchase_probability=30,
            done=False,
        ).model_dump_json(),
    )

    return {
        "scenario_id": scenario.id,
        "repository": repository,
        "supervisor_chain": chain,
        "get_customer_profile": lambda: "customer profile",
        "get_supervisor_prompt": lambda: "supervisor rules",
    }


def test_analyze_scenario_uses_visible_persisted_messages(tmp_path) -> None:
    chain = StubSupervisorChain(analysis())
    request = make_analysis_request(tmp_path, chain)

    result = asyncio.run(analyze_persisted_scenario(**request))

    assert result.overall_score == 82
    assert {key: value for key, value in chain.calls[0].items() if key != "analysis_contract"} == {
        "supervisor_prompt": "supervisor rules",
        "customer_profile": "customer profile",
        "conversation": (
            "1. [rm]\nЧто важно в текущем брокере?\n\n"
            "2. [client]\nМне нравятся низкие комиссии."
        ),
    }
    assert "КАЖДОЙ строки" in chain.calls[0]["analysis_contract"]


def test_analyze_scenario_requires_complete_message_review(tmp_path) -> None:
    incomplete = analysis().model_copy(update={"message_analyses": [analysis().message_analyses[0]]})
    request = make_analysis_request(tmp_path, StubSupervisorChain(incomplete))

    with pytest.raises(ValueError, match="каждую реплику"):
        asyncio.run(analyze_persisted_scenario(**request))

    assert len(request["supervisor_chain"].calls) == 2
    assert request["supervisor_chain"].calls[1]["analysis_contract"] == RETRY_SUPERVISOR_ANALYSIS_CONTRACT


def test_analyze_scenario_retries_incomplete_supervisor_report(tmp_path) -> None:
    complete = analysis()
    incomplete = complete.model_copy(update={"message_analyses": [complete.message_analyses[0]]})

    class RetryingChain:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.results = [incomplete, complete]

        async def ainvoke(self, values: dict[str, object], **_: object) -> SupervisorAnalysisData:
            self.calls.append(values)
            return self.results.pop(0)

    chain = RetryingChain()
    request = make_analysis_request(tmp_path, chain)

    result = asyncio.run(analyze_persisted_scenario(**request))

    assert result == complete
    assert len(chain.calls) == 2
    assert chain.calls[1]["analysis_contract"] == RETRY_SUPERVISOR_ANALYSIS_CONTRACT


def test_analyze_scenario_retries_english_supervisor_report(tmp_path) -> None:
    complete = analysis()
    english = complete.model_copy(deep=True)
    english.overall_assessment = "The RM opened the conversation effectively."
    english.message_analyses[0].assessment = "The question is relevant."
    english.message_analyses[0].recommendation = "Ask a follow-up question."
    english.message_analyses[1].assessment = "The client is cautious."
    english.message_analyses[1].recommendation = "Explore the client's concern."
    english.priority_recommendations = ["Continue discovery before presenting the product."]

    class RetryingChain:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.results = [english, complete]

        async def ainvoke(self, values: dict[str, object], **_: object) -> SupervisorAnalysisData:
            self.calls.append(values)
            return self.results.pop(0)

    chain = RetryingChain()
    request = make_analysis_request(tmp_path, chain)

    result = asyncio.run(analyze_persisted_scenario(**request))

    assert result == complete
    assert len(chain.calls) == 2
    assert chain.calls[1]["analysis_contract"] == RETRY_SUPERVISOR_ANALYSIS_CONTRACT


def test_analyze_scenario_rejects_unknown_scenario(tmp_path) -> None:
    settings = Settings(sqlite_path=tmp_path / "scenario.sqlite3", chat_storage_mode="sqlite")
    repository = ChatRepository(settings)
    repository.init_db()
    with pytest.raises(ScenarioNotFoundError):
        asyncio.run(
            analyze_persisted_scenario(
                scenario_id="missing",
                repository=repository,
                supervisor_chain=StubSupervisorChain(analysis()),
                get_customer_profile=lambda: "customer profile",
                get_supervisor_prompt=lambda: "supervisor rules",
            )
        )


def test_supervisor_analysis_errors_are_mapped_to_http_responses() -> None:
    assert supervisor_analysis_error(ScenarioNotFoundError("missing")).status_code == 404
    assert supervisor_analysis_error(ValueError("empty scenario")).status_code == 422

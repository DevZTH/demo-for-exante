from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from backend.app.agent_service import AgentService
from backend.app.api import analyze_scenario
from backend.app.schemas import AgentResponseData, SupervisorAnalysisData
from backend.app.storage import ChatRepository, ScenarioNotFoundError
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


def make_service(tmp_path, chain: StubSupervisorChain) -> tuple[AgentService, str]:
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

    service = AgentService.__new__(AgentService)
    service.repository = repository
    service.supervisor_chain = chain
    service._get_agent_system_prompt = lambda: "customer profile"
    service._get_supervisor_prompt = lambda: "supervisor rules"
    return service, scenario.id


def test_analyze_scenario_uses_visible_persisted_messages(tmp_path) -> None:
    chain = StubSupervisorChain(analysis())
    service, scenario_id = make_service(tmp_path, chain)

    result = asyncio.run(service.analyze_scenario(scenario_id))

    assert result.overall_score == 82
    assert chain.calls[0] == {
        "supervisor_prompt": "supervisor rules",
        "customer_profile": "customer profile",
        "conversation": (
            "1. [rm]\nЧто важно в текущем брокере?\n\n"
            "2. [client]\nМне нравятся низкие комиссии."
        ),
    }


def test_analyze_scenario_requires_complete_message_review(tmp_path) -> None:
    incomplete = analysis().model_copy(update={"message_analyses": [analysis().message_analyses[0]]})
    service, scenario_id = make_service(tmp_path, StubSupervisorChain(incomplete))

    with pytest.raises(ValueError, match="каждую реплику"):
        asyncio.run(service.analyze_scenario(scenario_id))


def test_analyze_scenario_rejects_unknown_scenario(tmp_path) -> None:
    settings = Settings(sqlite_path=tmp_path / "scenario.sqlite3", chat_storage_mode="sqlite")
    repository = ChatRepository(settings)
    repository.init_db()
    service = AgentService.__new__(AgentService)
    service.repository = repository

    with pytest.raises(ScenarioNotFoundError):
        asyncio.run(service.analyze_scenario("missing"))


class StubAnalysisService:
    def __init__(self, result: SupervisorAnalysisData | Exception) -> None:
        self.result = result
        self.requested_scenario_ids: list[str] = []

    async def analyze_scenario(self, scenario_id: str) -> SupervisorAnalysisData:
        self.requested_scenario_ids.append(scenario_id)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_analysis_api_returns_supervisor_report() -> None:
    service = StubAnalysisService(analysis())

    result = asyncio.run(analyze_scenario("scenario-1", service=service))

    assert result.overall_score == 82
    assert service.requested_scenario_ids == ["scenario-1"]


def test_analysis_api_returns_not_found_for_missing_scenario() -> None:
    service = StubAnalysisService(ScenarioNotFoundError("missing"))

    with pytest.raises(HTTPException) as error:
        asyncio.run(analyze_scenario("missing", service=service))

    assert error.value.status_code == 404


def test_analysis_api_returns_validation_error_for_empty_scenario() -> None:
    service = StubAnalysisService(
        ValueError("Невозможно проанализировать сценарий без реплик.")
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(analyze_scenario("empty", service=service))

    assert error.value.status_code == 422

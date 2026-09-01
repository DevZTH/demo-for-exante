from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from backend.app.api_errors import supervisor_analysis_error
from backend.app.agent_service import AgentService
from backend.app.domain import ScenarioRecord
from backend.app.scenario_access import get_existing_scenario, scenario_not_found_error
from backend.app.schemas import (
    MessageResponse,
    ScenarioResponse,
    ScenarioTurnRequest,
    ScenarioTurnResponse,
    SupervisorAnalysisData,
)
from backend.app.storage import ChatRepository, ScenarioNotFoundError


def get_repository(request: Request) -> ChatRepository:
    return request.app.state.repository


def get_agent_service(request: Request) -> AgentService:
    return request.app.state.agent_service


def get_existing_scenario_dependency(
    scenario_id: str,
    repository: ChatRepository = Depends(get_repository),
) -> ScenarioRecord:
    return get_existing_scenario(scenario_id, repository)


router = APIRouter(tags=["scenarios"])


@router.get("/health", tags=["system"])
def health(repository: ChatRepository = Depends(get_repository)) -> dict[str, object]:
    return {"status": "ok", "database": repository.health()}


@router.post("/scenarios/turns", response_model=ScenarioTurnResponse)
async def create_scenario_turn(
    request: ScenarioTurnRequest,
    service: AgentService = Depends(get_agent_service),
) -> ScenarioTurnResponse:
    """Process one Relationship Manager message in the EXANTE scenario."""
    try:
        turn, agent_response = await service.process_message(
            message=request.message,
            chat_id=request.scenario_id,
            metadata=request.metadata,
        )
    except ScenarioNotFoundError as exc:
        raise scenario_not_found_error() from exc

    return ScenarioTurnResponse.from_turn_and_agent(turn, agent_response)


@router.post(
    "/scenarios/{scenario_id}/analysis",
    response_model=SupervisorAnalysisData,
)
async def analyze_scenario(
    scenario_id: str,
    service: AgentService = Depends(get_agent_service),
) -> SupervisorAnalysisData:
    """Run the sales supervisor over the full persisted scenario history."""
    try:
        return await service.analyze_scenario(scenario_id)
    except (ScenarioNotFoundError, ValueError) as exc:
        raise supervisor_analysis_error(exc) from exc


@router.get("/scenarios", response_model=list[ScenarioResponse])
def list_scenarios(
    repository: ChatRepository = Depends(get_repository),
) -> list[ScenarioResponse]:
    return [
        ScenarioResponse.from_record(scenario)
        for scenario in repository.list_scenarios()
    ]


@router.get("/scenarios/{scenario_id}", response_model=ScenarioResponse)
def get_scenario(
    scenario: ScenarioRecord = Depends(get_existing_scenario_dependency),
) -> ScenarioResponse:
    return ScenarioResponse.from_record(scenario)


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(
    scenario: ScenarioRecord = Depends(get_existing_scenario_dependency),
    repository: ChatRepository = Depends(get_repository),
) -> None:
    if not repository.delete_scenario(scenario.id):
        raise scenario_not_found_error()


@router.get("/scenarios/{scenario_id}/messages", response_model=list[MessageResponse])
def list_scenario_messages(
    scenario: ScenarioRecord = Depends(get_existing_scenario_dependency),
    repository: ChatRepository = Depends(get_repository),
) -> list[MessageResponse]:
    return [
        MessageResponse.from_record(message)
        for message in repository.list_messages(scenario.id)
    ]

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.app.agent_service import AgentService
from backend.app.schemas import (
    MessageResponse,
    ScenarioResponse,
    ScenarioTurnRequest,
    ScenarioTurnResponse,
    SettingsResponse,
)
from backend.app.storage import ChatRepository, ScenarioNotFoundError
from backend.settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_repository(request: Request) -> ChatRepository:
    return request.app.state.repository


def get_agent_service(request: Request) -> AgentService:
    return request.app.state.agent_service


router = APIRouter(tags=["scenarios"])


@router.get("/health", tags=["system"])
def health(repository: ChatRepository = Depends(get_repository)) -> dict[str, object]:
    return {"status": "ok", "database": repository.health()}


@router.get("/settings", response_model=SettingsResponse, tags=["system"])
def read_settings(settings: Settings = Depends(get_settings)) -> SettingsResponse:
    return SettingsResponse(
        app_name=settings.app_name,
        api_prefix=settings.api_prefix,
        llm_provider="openai_compatible",
        llm_model=settings.llm_model,
        llm_endpoint=settings.llm_base_url,
        chat_storage_mode=settings.chat_storage_mode,
        history_window_messages=settings.history_window_messages,
        semantic_memory_limit=settings.semantic_memory_limit,
        embedding_dimensions=settings.embedding_dimensions,
    )


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scenario not found",
        ) from exc

    return ScenarioTurnResponse.from_turn_and_agent(turn, agent_response)


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
    scenario_id: str,
    repository: ChatRepository = Depends(get_repository),
) -> ScenarioResponse:
    scenario = repository.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    return ScenarioResponse.from_record(scenario)


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(
    scenario_id: str,
    repository: ChatRepository = Depends(get_repository),
) -> None:
    if not repository.delete_scenario(scenario_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")


@router.get("/scenarios/{scenario_id}/messages", response_model=list[MessageResponse])
def list_scenario_messages(
    scenario_id: str,
    repository: ChatRepository = Depends(get_repository),
) -> list[MessageResponse]:
    if repository.get_scenario(scenario_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    return [
        MessageResponse.from_record(message)
        for message in repository.list_messages(scenario_id)
    ]

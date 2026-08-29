from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.app.chat_engine import ChatEngine
from backend.app.schemas import (
    ChatCreateRequest,
    ChatRequest,
    ChatResponse,
    ChatTurnResponse,
    MessageResponse,
    SettingsResponse,
)
from backend.app.storage import ChatRepository
from backend.settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_repository(request: Request) -> ChatRepository:
    return request.app.state.repository


def get_chat_engine(request: Request) -> ChatEngine:
    return request.app.state.chat_engine


router = APIRouter(tags=["chat"])


@router.get("/health", tags=["system"])
def health(repository: ChatRepository = Depends(get_repository)) -> dict[str, object]:
    return {"status": "ok", "database": repository.health()}


@router.get("/settings", response_model=SettingsResponse, tags=["system"])
def read_settings(settings: Settings = Depends(get_settings)) -> SettingsResponse:
    return SettingsResponse(
        app_name=settings.app_name,
        api_prefix=settings.api_prefix,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        llm_endpoint=_llm_endpoint(settings),
        chat_storage_mode=settings.chat_storage_mode,
        history_window_messages=settings.history_window_messages,
        semantic_memory_limit=settings.semantic_memory_limit,
        embedding_dimensions=settings.embedding_dimensions,
    )


def _llm_endpoint(settings: Settings) -> str:
    if settings.llm_provider == "demo":
        return "local"
    if settings.llm_provider == "ollama":
        return settings.ollama_base_url
    if settings.llm_provider == "openrouter":
        return settings.openrouter_base_url
    return settings.openai_base_url


@router.post("/chat", response_model=ChatTurnResponse)
async def chat(
    request: ChatRequest,
    engine: ChatEngine = Depends(get_chat_engine),
) -> ChatTurnResponse:
    turn = await engine.ask(
        message=request.message,
        chat_id=request.chat_id,
        metadata=request.metadata,
    )
    return ChatTurnResponse.from_turn(turn)


@router.post(
    "/chats",
    response_model=ChatResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_chat(
    request: ChatCreateRequest,
    repository: ChatRepository = Depends(get_repository),
) -> ChatResponse:
    return ChatResponse.from_record(repository.create_chat(title=request.title))


@router.get("/chats", response_model=list[ChatResponse])
def list_chats(repository: ChatRepository = Depends(get_repository)) -> list[ChatResponse]:
    return [ChatResponse.from_record(chat) for chat in repository.list_chats()]


@router.get("/chats/{chat_id}", response_model=ChatResponse)
def get_chat(
    chat_id: str,
    repository: ChatRepository = Depends(get_repository),
) -> ChatResponse:
    chat_record = repository.get_chat(chat_id)
    if chat_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return ChatResponse.from_record(chat_record)


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(chat_id: str, repository: ChatRepository = Depends(get_repository)) -> None:
    if not repository.delete_chat(chat_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")


@router.get("/chats/{chat_id}/messages", response_model=list[MessageResponse])
def list_messages(
    chat_id: str,
    repository: ChatRepository = Depends(get_repository),
) -> list[MessageResponse]:
    if repository.get_chat(chat_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return [
        MessageResponse.from_record(message)
        for message in repository.list_messages(chat_id)
    ]

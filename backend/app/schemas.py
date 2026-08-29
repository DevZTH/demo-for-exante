from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.domain import ChatRecord, ChatTurn, MessageRecord, SemanticMatch


class ChatCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ChatResponse(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: ChatRecord) -> "ChatResponse":
        return cls(
            id=record.id,
            title=record.title,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class MessageResponse(BaseModel):
    id: int
    chat_id: str
    role: Literal["system", "user", "assistant"]
    content: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(cls, record: MessageRecord) -> "MessageResponse":
        return cls(
            id=record.id,
            chat_id=record.chat_id,
            role=record.role,
            content=record.content,
            created_at=record.created_at,
            metadata=record.metadata,
        )


class SemanticMatchResponse(BaseModel):
    message: MessageResponse
    distance: float

    @classmethod
    def from_match(cls, match: SemanticMatch) -> "SemanticMatchResponse":
        return cls(
            message=MessageResponse.from_record(match.message),
            distance=match.distance,
        )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    chat_id: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatTurnResponse(BaseModel):
    chat: ChatResponse
    user_message: MessageResponse
    assistant_message: MessageResponse
    context: list[SemanticMatchResponse]
    provider: str
    model: str

    @classmethod
    def from_turn(cls, turn: ChatTurn) -> "ChatTurnResponse":
        return cls(
            chat=ChatResponse.from_record(turn.chat),
            user_message=MessageResponse.from_record(turn.user_message),
            assistant_message=MessageResponse.from_record(turn.assistant_message),
            context=[SemanticMatchResponse.from_match(match) for match in turn.context],
            provider=turn.provider,
            model=turn.model,
        )


class SettingsResponse(BaseModel):
    app_name: str
    api_prefix: str
    llm_provider: str
    llm_model: str
    llm_endpoint: str
    chat_storage_mode: str
    history_window_messages: int
    semantic_memory_limit: int
    embedding_dimensions: int

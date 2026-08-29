from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ChatRecord:
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MessageRecord:
    id: int
    chat_id: str
    role: str
    content: str
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticMatch:
    message: MessageRecord
    distance: float


@dataclass(frozen=True)
class ChatTurn:
    chat: ChatRecord
    user_message: MessageRecord
    assistant_message: MessageRecord
    context: list[SemanticMatch]
    provider: str
    model: str


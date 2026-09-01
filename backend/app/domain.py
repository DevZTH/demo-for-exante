from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ScenarioRecord:
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
class ScenarioTurn:
    scenario: ScenarioRecord
    user_message: MessageRecord
    assistant_message: MessageRecord
    context: list[SemanticMatch]
    provider: str
    model: str


def assistant_reply_or_fallback(
    content: str,
    *,
    fallback: str,
    parser: Callable[[str], object] | None = None,
) -> str:
    """Return a stored assistant reply without exposing its internal state."""
    try:
        payload = parser(content) if parser else json.loads(content)
    except ValueError:
        return fallback

    reply = payload.get("reply") if isinstance(payload, dict) else getattr(payload, "reply", None)
    return reply if isinstance(reply, str) else fallback

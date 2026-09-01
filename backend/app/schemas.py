from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.domain import (
    MessageRecord,
    ScenarioRecord,
    ScenarioTurn,
    SemanticMatch,
    assistant_reply_or_fallback,
)


class ScenarioResponse(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: ScenarioRecord) -> "ScenarioResponse":
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
            content=_visible_content(record),
            created_at=record.created_at,
            metadata=record.metadata,
        )


def _visible_content(record: MessageRecord) -> str:
    """Do not expose the customer model's internal state as message text."""
    return (
        assistant_reply_or_fallback(
            record.content,
            fallback="Ответ клиента недоступен.",
        )
        if record.role == "assistant"
        else record.content
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


class AgentResponseData(BaseModel):
    """Structured customer response for the EXANTE exercise."""

    reply: str = Field(description="Customer reply to the Relationship Manager")
    intetions: str = Field(description="Internal customer state (hidden from RM)")
    state: Literal[
        "curious",
        "considering",
        "interested",
        "evaluating",
        "ready_for_next_step",
        "ready_to_fund",
        "rejected",
    ] = Field(description="Current customer engagement stage")
    trust: int = Field(ge=0, le=100, description="Trust level in RM (0-100)")
    purchase_probability: int = Field(
        ge=0,
        le=100,
        description="Probability of opening an account (0-100)",
    )
    done: bool = Field(description="Whether the conversation is complete")


class SupervisorMessageAnalysis(BaseModel):
    """Supervisor feedback for one spoken message in the scenario."""

    message_number: int = Field(
        ge=1,
        description="One-based number of the message in the supplied conversation",
    )
    speaker: Literal["rm", "client"] = Field(
        description="Speaker of the analysed message",
    )
    score: int = Field(
        ge=0,
        le=10,
        description="RM quality or client engagement signal on a 0–10 scale",
    )
    assessment: str = Field(
        min_length=1,
        description="Concise explanation based only on the message and its context",
    )
    recommendation: str = Field(
        min_length=1,
        description="Concrete next-step coaching for the RM",
    )


class SupervisorAnalysisData(BaseModel):
    """Whole-conversation coaching produced by the supervisor role."""

    overall_score: int = Field(
        ge=0,
        le=100,
        description="Overall RM performance for the conversation",
    )
    overall_assessment: str = Field(
        min_length=1,
        description="Summary of the conversation outcome and the main reason for it",
    )
    message_analyses: list[SupervisorMessageAnalysis] = Field(
        description="One analysis for every message in chronological order",
    )
    priority_recommendations: list[str] = Field(
        min_length=1,
        description="Most important actions for the RM in the next conversation",
    )


class ScenarioTurnRequest(BaseModel):
    """A Relationship Manager message in an EXANTE scenario."""

    message: str = Field(min_length=1, max_length=20_000, description="RM message")
    scenario_id: str | None = Field(
        default=None,
        max_length=120,
        description="Existing scenario ID; omit it to start a scenario",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional message metadata",
    )


class ScenarioTurnResponse(BaseModel):
    """A stored scenario turn and the customer evaluation signal."""

    scenario: ScenarioResponse
    user_message: MessageResponse
    assistant_message: MessageResponse
    agent_response: AgentResponseData
    context: list[SemanticMatchResponse]
    provider: str
    model: str

    @classmethod
    def from_turn_and_agent(
        cls,
        turn: ScenarioTurn,
        agent_response: AgentResponseData,
    ) -> "ScenarioTurnResponse":
        return cls(
            scenario=ScenarioResponse.from_record(turn.scenario),
            user_message=MessageResponse.from_record(turn.user_message),
            assistant_message=MessageResponse.from_record(turn.assistant_message),
            agent_response=agent_response,
            context=[SemanticMatchResponse.from_match(match) for match in turn.context],
            provider=turn.provider,
            model=turn.model,
        )

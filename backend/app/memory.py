from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from backend.app.domain import MessageRecord
from backend.app.storage import ChatRepository


class SQLiteScenarioMessageHistory(BaseChatMessageHistory):
    """LangChain scenario history backed by the project SQLite repository."""

    def __init__(
        self,
        *,
        repository: ChatRepository,
        chat_id: str,
        history_limit: int,
        embeddings: Embeddings,
        user_metadata: dict[str, Any] | None = None,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.repository = repository
        self.chat_id = chat_id
        self.history_limit = history_limit
        self.embeddings = embeddings
        self.user_metadata = user_metadata or {}
        self.assistant_metadata = assistant_metadata or {}
        self.added_records: list[MessageRecord] = []

    @property
    def messages(self) -> list[BaseMessage]:
        records = self.repository.list_messages(
            self.chat_id,
            limit=self.history_limit,
        )
        return [to_langchain_message(record) for record in records]

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        for message in messages:
            role = role_from_langchain_message(message)
            content = content_from_langchain_message(message)
            metadata = self._metadata_for(role)
            embedding_content = visible_content_for_role(role, content)
            embedding = self.embeddings.embed_query(embedding_content) if embedding_content else None

            self.added_records.append(
                self.repository.add_message(
                    self.chat_id,
                    role,
                    content,
                    metadata=metadata,
                    embedding=embedding,
                )
            )

    def clear(self) -> None:
        self.repository.clear_messages(self.chat_id)
        self.added_records = []

    def _metadata_for(self, role: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {"memory": "langchain"}
        if role == "user":
            metadata.update(self.user_metadata)
        if role == "assistant":
            metadata.update(self.assistant_metadata)
        return metadata


def to_langchain_message(record: MessageRecord) -> BaseMessage:
    if record.role == "user":
        return HumanMessage(content=record.content)
    if record.role == "assistant":
        return AIMessage(content=visible_content_for_role(record.role, record.content))
    if record.role == "system":
        return SystemMessage(content=record.content)
    raise ValueError(f"Unsupported message role: {record.role}")


def role_from_langchain_message(message: BaseMessage) -> str:
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, SystemMessage):
        return "system"
    message_type = getattr(message, "type", "")
    if message_type == "human":
        return "user"
    if message_type == "ai":
        return "assistant"
    if message_type == "system":
        return "system"
    raise ValueError(f"Unsupported LangChain message type: {message_type}")


def content_from_langchain_message(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(item) for item in content)
    return str(content)


def visible_content_for_role(role: str, content: str) -> str:
    if role != "assistant":
        return content

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return "Ответ клиента из предыдущего сообщения недоступен."

    reply = payload.get("reply") if isinstance(payload, dict) else None
    return reply if isinstance(reply, str) else "Ответ клиента из предыдущего сообщения недоступен."

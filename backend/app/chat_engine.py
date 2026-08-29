from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from backend.app.domain import ChatTurn, MessageRecord, SemanticMatch
from backend.app.embeddings import HashEmbeddings
from backend.app.memory import SQLiteChatMessageHistory
from backend.app.providers import build_chat_model
from backend.app.storage import ChatRepository
from backend.settings import Settings


class ChatEngine:
    def __init__(self, settings: Settings, repository: ChatRepository) -> None:
        self.settings = settings
        self.repository = repository
        self.embeddings = HashEmbeddings(settings.embedding_dimensions)
        self.llm = build_chat_model(settings)
        self.chain = self._build_chain()

    async def ask(
        self,
        *,
        message: str,
        chat_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatTurn:
        chat = self.repository.ensure_chat(chat_id, title=self._title_from(message))
        query_embedding = self.embeddings.embed_query(message)
        semantic_context = self._semantic_context(chat.id, query_embedding)
        history = SQLiteChatMessageHistory(
            repository=self.repository,
            chat_id=chat.id,
            history_limit=self.settings.history_window_messages,
            embeddings=self.embeddings,
            user_metadata=metadata,
            assistant_metadata={
                "provider": self.settings.llm_provider,
                "model": self.settings.llm_model,
            },
        )

        response = await self.chain.ainvoke(
            {
                "system_prompt": self.settings.system_prompt,
                "semantic_context": self._format_semantic_context(semantic_context),
                "history": history.messages,
                "input": message,
            }
        )

        answer = self._content_from_response(response)
        history.add_messages([HumanMessage(content=message), AIMessage(content=answer)])
        user_message, assistant_message = self._saved_turn(history.added_records)

        updated_chat = self.repository.get_chat(chat.id)
        if updated_chat is None:
            raise RuntimeError("Chat disappeared after writing messages")

        return ChatTurn(
            chat=updated_chat,
            user_message=user_message,
            assistant_message=assistant_message,
            context=semantic_context,
            provider=self.settings.llm_provider,
            model=self.settings.llm_model,
        )

    def _build_chain(self):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{system_prompt}"),
                (
                    "system",
                    "Relevant earlier messages from semantic memory:\n{semantic_context}",
                ),
                MessagesPlaceholder("history"),
                ("human", "{input}"),
            ]
        )
        return prompt | self.llm

    def _semantic_context(
        self,
        chat_id: str,
        query_embedding: list[float],
    ) -> list[SemanticMatch]:
        if not self.repository.vector_enabled:
            return []

        return self.repository.search_similar_messages(
            chat_id,
            query_embedding,
            limit=self.settings.semantic_memory_limit,
        )

    @staticmethod
    def _format_semantic_context(matches: list[SemanticMatch]) -> str:
        if not matches:
            return "No earlier relevant messages."

        return "\n".join(
            f"- {match.message.role}: {match.message.content}"
            for match in matches
        )

    @staticmethod
    def _content_from_response(response: object) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(item) for item in content)
        return str(content)

    @staticmethod
    def _saved_turn(records: list[MessageRecord]) -> tuple[MessageRecord, MessageRecord]:
        user_message = next((record for record in records if record.role == "user"), None)
        assistant_message = next(
            (record for record in records if record.role == "assistant"),
            None,
        )

        if user_message is None or assistant_message is None:
            raise RuntimeError("LangChain memory did not persist the chat turn")

        return user_message, assistant_message

    @staticmethod
    def _title_from(message: str) -> str:
        compact = " ".join(message.split())
        return compact[:80] or "New chat"

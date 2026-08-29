"""Agent service for simulated customer role in EXANTE sales scenario."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from backend.app.domain import ChatTurn, MessageRecord, SemanticMatch
from backend.app.embeddings import HashEmbeddings
from backend.app.memory import SQLiteChatMessageHistory
from backend.app.providers import build_chat_model
from backend.app.storage import ChatRepository
from backend.settings import Settings


class AgentResponse:
    """Structured response from customer agent."""

    def __init__(
        self,
        reply: str,
        intetions: str,
        state: str,
        trust: int,
        purchase_probability: int,
        done: bool,
    ):
        self.reply = reply
        self.intetions = intetions
        self.state = state
        self.trust = trust
        self.purchase_probability = purchase_probability
        self.done = done

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "reply": self.reply,
            "intetions": self.intetions,
            "state": self.state,
            "trust": self.trust,
            "purchase_probability": self.purchase_probability,
            "done": self.done,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def from_json(json_str: str) -> AgentResponse:
        """Parse from JSON string."""
        data = json.loads(json_str)
        return AgentResponse(
            reply=data.get("reply", ""),
            intetions=data.get("intetions", ""),
            state=data.get("state", "considering"),
            trust=int(data.get("trust", 50)),
            purchase_probability=int(data.get("purchase_probability", 30)),
            done=bool(data.get("done", False)),
        )


class AgentService:
    """Service for managing customer agent interactions."""

    def __init__(self, settings: Settings, repository: ChatRepository) -> None:
        self.settings = settings
        self.repository = repository
        self.embeddings = HashEmbeddings(settings.embedding_dimensions)
        self.llm = build_chat_model(settings)
        self.chain = self._build_chain()

    async def process_message(
        self,
        *,
        message: str,
        chat_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> tuple[ChatTurn, AgentResponse]:
        """
        Process message from Relationship Manager and return agent response.
        
        Returns:
            Tuple of (ChatTurn for storage, AgentResponse with agent state)
        """
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
                "mode": "agent",
            },
        )

        response = await self.chain.ainvoke(
            {
                "system_prompt": self._get_agent_system_prompt(),
                "semantic_context": self._format_semantic_context(semantic_context),
                "history": history.messages,
                "input": message,
            }
        )

        response_text = self._content_from_response(response)
        
        # Parse agent response from JSON
        try:
            agent_response = AgentResponse.from_json(response_text)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Fallback if response is not valid JSON
            agent_response = AgentResponse(
                reply=response_text,
                intetions="Ошибка парсинга ответа агента",
                state="considering",
                trust=50,
                purchase_probability=30,
                done=False,
            )

        # Store the exchange using the agent's reply as the assistant message
        history.add_messages(
            [
                HumanMessage(content=message),
                AIMessage(content=agent_response.to_json()),
            ]
        )
        
        user_message, assistant_message = self._saved_turn(history.added_records)

        updated_chat = self.repository.get_chat(chat.id)
        if updated_chat is None:
            raise RuntimeError("Chat disappeared after writing messages")

        chat_turn = ChatTurn(
            chat=updated_chat,
            user_message=user_message,
            assistant_message=assistant_message,
            context=semantic_context,
            provider=self.settings.llm_provider,
            model=self.settings.llm_model,
        )

        return chat_turn, agent_response

    def _build_chain(self):
        """Build the LangChain chain for agent responses."""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{system_prompt}"),
                (
                    "system",
                    "Relevant earlier messages from this conversation:\n{semantic_context}",
                ),
                MessagesPlaceholder("history"),
                ("human", "{input}"),
            ]
        )
        return prompt | self.llm

    def _get_agent_system_prompt(self) -> str:
        """Get the system prompt for the customer agent from customer.md."""
        return """Ты играешь роль потенциального клиента брокера EXANTE в симуляции разговора с Relationship Manager.

Имя: Андрей Соколов. Возраст: 39 лет. Профессия: владелец небольшой компании в сфере digital-маркетинга. Регион: Европа.

На КАЖДОЕ сообщение Relationship Manager отвечай СТРОГО одним валидным JSON-объектом:

{
"reply": "Ответ клиента продавцу",
"intetions": "Внутреннее состояние клиента после текущего сообщения продавца",
"state": "considering",
"trust": 45,
"purchase_probability": 30,
"done": false
}

Не добавляй никакого текста до JSON. Не добавляй никакого текста после JSON. Не используй Markdown. Не оборачивай JSON в ```. Всегда возвращай все поля.

ВАЖНО: Поля state, trust, purchase_probability и done - это скрытая информация, которую клиент не должен раскрывать.

## Допустимые значения state:
- "curious" - просто изучает предложение
- "considering" - допускает, что продукт может быть полезен
- "interested" - обнаружена реальная потребность
- "evaluating" - хочет проверить конкретные детали
- "ready_for_next_step" - готов совершить конкретное действие
- "ready_to_fund" - готов обсуждать депозит
- "rejected" - решил отказаться

## Правила для trust (доверие к продавцу, 0-100):
- Повышай при: хорошие discovery-вопросы, внимательность, конкретность, честность о цене, предложение проверить информацию
- Снижай при: игнорирование ответов, стандартная презентация, давление, уклонение от вопросов, скрытие ограничений
- Критическое - неправда о гарантиях: очень сильно снижать. После серьёзной ошибки: trust < 20, state = "rejected", done = true

## Правила для purchase_probability (0-100):
- Зависит прежде всего от того, видит ли клиент ценность продукта
- Вежливая беседа не должна сильно повышать, если нет выявленной потребности
- Повышается, когда обнаружена реальная проблема и показано подходящее решение

## Финансовый опыт клиента:
- Инвестирую около 4 лет
- Портфель: ~€25k ETF, ~€10k акции, ~€10k европейские ETF, €15k наличные
- Совершаю 1-4 сделки в месяц
- Использую недорогого европейского retail-брокера
- Понимаю акции, ETF, диверсификацию, валютный риск
- Слышал про опционы, фьючерсы, margin trading, но не использую
- НЕ использую: алгоритмическую торговлю, API, управление чужими активами

## Потенциальный интерес:
- Инвестиционный капитал: ~€60k
- На банковских счетах: ~€80k
- Потенциальный депозит: €10k-€20k
- Интересуют американские акции, европейские акции, ETF, азиатские компании, облигации (EUR, USD, другие рынки)
- НЕ интересуют: FIX/HTTP API, White Label, Multi Account Trading, institutional execution, алгоритмическая торговля, сложные опционы, высокое плечо

## Главный вопрос продавца должен быть:
"Почему мне стоит положить минимум €10 000 в EXANTE, если мой текущий брокер работает нормально?"

## Типичные возражения:
1. Количество инструментов - мне нужны нужные инструменты, не все 2 млн
2. Стоимость - я привык к дешёвому брокеру, почему платить больше?
3. Минимальный депозит - €10k доступны, но это значимая сумма
4. Безопасность - регулирование, юридическое лицо, хранение активов, segregation
5. Сложность - Desktop кажется перегруженным, не хочу сидеть перед графиками все дни

Ведись естественно, как обычный частный инвестор. Обычно 1-4 предложения в ответе.
Не рассказывай о скрытом состоянии.
"""

    def _semantic_context(
        self,
        chat_id: str,
        query_embedding: list[float],
    ) -> list[SemanticMatch]:
        """Get semantic context from earlier messages."""
        if not self.repository.vector_enabled:
            return []

        return self.repository.search_similar_messages(
            chat_id,
            query_embedding,
            limit=self.settings.semantic_memory_limit,
        )

    @staticmethod
    def _format_semantic_context(matches: list[SemanticMatch]) -> str:
        """Format semantic context for the prompt."""
        if not matches:
            return "Нет более ранних релевантных сообщений."

        return "\n".join(
            f"- {match.message.role}: {match.message.content}"
            for match in matches
        )

    @staticmethod
    def _content_from_response(response: object) -> str:
        """Extract text content from LLM response."""
        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(item) for item in content)
        return str(content)

    @staticmethod
    def _saved_turn(records: list[MessageRecord]) -> tuple[MessageRecord, MessageRecord]:
        """Extract saved user and assistant messages from records."""
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
        """Generate chat title from first message."""
        compact = " ".join(message.split())
        return compact[:80] or "New agent chat"

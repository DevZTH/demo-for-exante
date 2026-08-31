"""Agent service for simulated customer role in EXANTE sales scenario."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from backend.app.domain import MessageRecord, ScenarioTurn, SemanticMatch
from backend.app.embeddings import LocalHashEmbeddings
from backend.app.memory import SQLiteScenarioMessageHistory
from backend.app.providers import build_chat_model
from backend.app.schemas import AgentResponseData, SupervisorAnalysisData
from backend.app.storage import ChatRepository, ScenarioNotFoundError
from backend.app.supervisor_contract import (
    INITIAL_SUPERVISOR_ANALYSIS_CONTRACT,
    RETRY_SUPERVISOR_ANALYSIS_CONTRACT,
    validate_supervisor_report_language,
)
from backend.settings import Settings


class AgentService:
    """Service for managing customer agent interactions."""

    def __init__(
        self,
        settings: Settings,
        repository: ChatRepository,
        langfuse_client: Any | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.langfuse = langfuse_client
        self.embeddings = LocalHashEmbeddings(settings.embedding_dimensions)
        self.llm = build_chat_model(settings)
        self.chain = self._build_chain()
        self.supervisor_chain = self._build_supervisor_chain()

    async def analyze_scenario(self, scenario_id: str) -> SupervisorAnalysisData:
        """Produce coaching for every visible message in one saved scenario."""
        self.repository.require_scenario(scenario_id)
        messages = [
            message
            for message in self.repository.list_messages(scenario_id)
            if message.role in {"user", "assistant"}
        ]
        if not messages:
            raise ValueError("Невозможно проанализировать сценарий без реплик.")

        request = {
            "supervisor_prompt": self._get_supervisor_prompt(),
            "customer_profile": self._get_agent_system_prompt(),
            "conversation": self._format_conversation_for_supervisor(messages),
        }
        contracts = (
            INITIAL_SUPERVISOR_ANALYSIS_CONTRACT,
            RETRY_SUPERVISOR_ANALYSIS_CONTRACT,
        )
        for contract in contracts:
            result = await self.supervisor_chain.ainvoke(
                {**request, "analysis_contract": contract},
                config={"run_name": "analyze-scenario"},
            )
            try:
                analysis = (
                    result
                    if isinstance(result, SupervisorAnalysisData)
                    else SupervisorAnalysisData.model_validate(result)
                )
                self._validate_supervisor_analysis(analysis, messages)
                validate_supervisor_report_language(analysis)
                return analysis
            except ValueError:
                if contract == contracts[-1]:
                    raise

        raise RuntimeError("Не удалось сформировать отчёт супервайзера")

    async def process_message(
        self,
        *,
        message: str,
        chat_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> tuple[ScenarioTurn, AgentResponseData]:
        """
        Process message from Relationship Manager and return agent response.
        
        Returns:
            Tuple of (ScenarioTurn for storage, AgentResponseData with agent state)
        """
        scenario = (
            self.repository.require_scenario(chat_id)
            if chat_id
            else self.repository.create_scenario(title=self._title_from(message))
        )

        if self.langfuse is None:
            return await self._process_scenario_turn(
                scenario_id=scenario.id,
                message=message,
                metadata=metadata,
            )

        # The root agent observation makes one API turn a compact trace. The
        # scenario ID is a stable session ID, so the Langfuse Sessions view
        # reconstructs the full multi-turn conversation.
        from langfuse import propagate_attributes

        with propagate_attributes(
            trace_name="scenario-turn",
            session_id=scenario.id,
            tags=["scenario-trainer", "customer-agent"],
        ):
            with self.langfuse.start_as_current_observation(
                as_type="agent",
                name="respond-to-manager",
                input={"message": message},
                metadata={
                    "feature": "scenario-trainer",
                    "provider": "openai_compatible",
                    "model": self.settings.llm_model,
                    "storage_mode": self.settings.chat_storage_mode,
                },
            ) as agent_observation:
                turn, agent_response = await self._process_scenario_turn(
                    scenario_id=scenario.id,
                    message=message,
                    metadata=metadata,
                    callback_handler=self._langfuse_callback_handler(),
                )
                # The trace table should show the spoken response, not the
                # structured model payload or unrelated function arguments.
                agent_observation.update(output={"reply": agent_response.reply})
                return turn, agent_response

    async def _process_scenario_turn(
        self,
        *,
        scenario_id: str,
        message: str,
        metadata: dict[str, object] | None,
        callback_handler: Any | None = None,
    ) -> tuple[ScenarioTurn, AgentResponseData]:
        semantic_context = self._get_semantic_context(scenario_id, message)

        history = SQLiteScenarioMessageHistory(
            repository=self.repository,
            chat_id=scenario_id,
            history_limit=self.settings.history_window_messages,
            embeddings=self.embeddings,
            user_metadata=metadata,
            assistant_metadata={
                "provider": "openai_compatible",
                "model": self.settings.llm_model,
                "scenario": "exante-sales",
            },
        )

        config: dict[str, object] = {"run_name": "generate-customer-response"}
        if callback_handler is not None:
            config["callbacks"] = [callback_handler]

        response = await self.chain.ainvoke(
            {
                "system_prompt": self._get_agent_system_prompt(),
                "semantic_context": self._format_semantic_context(semantic_context),
                "history": history.messages,
                "input": message,
            },
            config=config,
        )

        agent_response = (
            response
            if isinstance(response, AgentResponseData)
            else AgentResponseData.model_validate(response)
        )

        # Store the exchange using the agent's reply as the assistant message
        history.add_messages(
            [
                HumanMessage(content=message),
                AIMessage(content=agent_response.model_dump_json()),
            ]
        )
        
        user_message, assistant_message = self._saved_turn(history.added_records)

        updated_scenario = self.repository.get_scenario(scenario_id)
        if updated_scenario is None:
            raise ScenarioNotFoundError(scenario_id)

        scenario_turn = ScenarioTurn(
            scenario=updated_scenario,
            user_message=user_message,
            assistant_message=assistant_message,
            context=semantic_context,
            provider="openai_compatible",
            model=self.settings.llm_model,
        )

        return scenario_turn, agent_response

    def _get_semantic_context(
        self,
        scenario_id: str,
        message: str,
    ) -> list[SemanticMatch]:
        if self.langfuse is None:
            return self._semantic_context(
                scenario_id,
                self.embeddings.embed_query(message),
            )

        with self.langfuse.start_as_current_observation(
            as_type="retriever",
            name="retrieve-semantic-context",
            input={"query": message},
        ) as retrieval:
            matches = self._semantic_context(
                scenario_id,
                self.embeddings.embed_query(message),
            )
            retrieval.update(
                output={
                    "match_count": len(matches),
                    "message_ids": [match.message.id for match in matches],
                    "distances": [round(match.distance, 6) for match in matches],
                }
            )
            return matches

    @staticmethod
    def _langfuse_callback_handler() -> Any:
        # A handler is deliberately created for each invocation; Langfuse warns
        # that shared handlers are unsafe when requests run concurrently.
        from langfuse.langchain import CallbackHandler

        return CallbackHandler()

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
        return prompt | self.llm.with_structured_output(AgentResponseData)

    def _build_supervisor_chain(self):
        """Build the independent structured coaching chain."""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{supervisor_prompt}"),
                ("system", "<customer_profile>\n{customer_profile}\n</customer_profile>"),
                ("system", "<analysis_contract>\n{analysis_contract}\n</analysis_contract>"),
                ("human", "<conversation>\n{conversation}\n</conversation>"),
            ]
        )
        return prompt | self.llm.with_structured_output(SupervisorAnalysisData)

    def _get_agent_system_prompt(self) -> str:
        """Get the system prompt for the customer agent from customer.md."""
        with open("backend/agent/customer.md", "r", encoding="utf-8") as f:
            retval = f.read()
        return retval

    def _get_supervisor_prompt(self) -> str:
        """Get the coaching rules for the supervisor role."""
        with open("backend/agent/supervisor.md", "r", encoding="utf-8") as f:
            return f.read()

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
            f"- {match.message.role}: {_visible_context_content(match.message)}"
            for match in matches
        )

    @staticmethod
    def _format_conversation_for_supervisor(messages: Sequence[MessageRecord]) -> str:
        """Render persisted messages in the same explicit format as the CLI."""
        transcript: list[str] = []
        for number, message in enumerate(messages, start=1):
            speaker = "rm" if message.role == "user" else "client"
            transcript.append(
                f"{number}. [{speaker}]\n{_visible_context_content(message)}"
            )
        return "\n\n".join(transcript)

    @staticmethod
    def _validate_supervisor_analysis(
        analysis: SupervisorAnalysisData,
        messages: Sequence[MessageRecord],
    ) -> None:
        """Require coaching feedback for every message, in chronological order."""
        expected = [
            (number, "rm" if message.role == "user" else "client")
            for number, message in enumerate(messages, start=1)
        ]
        actual = [
            (item.message_number, item.speaker)
            for item in analysis.message_analyses
        ]
        if actual != expected:
            raise ValueError(
                "супервайзер должен разобрать каждую реплику в исходном порядке"
            )

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
        return compact[:80] or "Новый сценарий EXANTE"


def _visible_context_content(message: MessageRecord) -> str:
    if message.role != "assistant":
        return message.content

    try:
        return AgentResponseData.model_validate_json(message.content).reply
    except ValueError:
        return "Ответ клиента из предыдущего сообщения недоступен."

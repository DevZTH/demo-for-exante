"""Langfuse experiment for the EXANTE sales simulation.

The tested agent is the customer persona from ``backend/agent/customer.md``.
For each scenario, a second LLM acts as the Relationship Manager. Its system
prompt is loaded from the repository-level ``seller.md`` and it must conduct
the dialogue according to those sales and compliance rules.

Each case gets an isolated SQLite database with the same short-term and
semantic memory that the API uses:

* SQLiteScenarioMessageHistory supplies the dialogue window;
* LocalHashEmbeddings + sqlite-vec retrieve relevant earlier messages.

Run from the repository root:
    python backend/lftest.py

Or from backend/:
    python lftest.py

Set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL before
running it. A live model call is made for both agents on every dialogue turn.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from typing import Any, Sequence

# Make `backend.*` imports work both from the project root and from backend/.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from backend.app.embeddings import LocalHashEmbeddings
from backend.app.memory import SQLiteScenarioMessageHistory
from backend.app.providers import build_chat_model
from backend.app.schemas import AgentResponseData
from backend.app.storage import ChatRepository
from backend.cli import read_system_prompt
from backend.settings import Settings, get_settings


SELLER_PROMPT_PATH = PROJECT_ROOT / "seller.md"
ENV_PATH = PROJECT_ROOT / "backend" / ".env"
MANAGER_PROMPT_SECTIONS = frozenset(
    {
        "Роль",
        "База продукта",
        "Стиль общения",
        "Обязательные правила комплаенса",
    }
)
# The local model is configured with a 4K context. Keep the immediate dialogue
# window compact and let semantic retrieval cover older turns.
EVALUATION_HISTORY_WINDOW_MESSAGES = 2
EVALUATION_SEMANTIC_MEMORY_LIMIT = 1
SEMANTIC_CONTEXT_MESSAGE_CHARS = 600


LOCAL_CASES: list[dict[str, Any]] = [
    {
        "input": {
            "id": "discovery-multicurrency",
            "manager_brief": (
                "Первый разговор с Андреем. Проведите discovery, не читайте презентацию. "
                "Проверьте, есть ли у клиента разрозненные счета/валюты и нужна ли ему "
                "инфраструктура для растущего портфеля. Если уместно, предложите безопасный "
                "следующий шаг вместо давления на открытие счёта."
            ),
            "max_turns": 5,
        },
        "expected_output": {
            "allowed_states": [
                "considering",
                "interested",
                "evaluating",
                "ready_for_next_step",
                "ready_to_fund",
            ],
            "done": False,
            "trust_min": 30,
            "purchase_probability_min": 30,
            "semantic_memory_required": True,
            "manager_discovery_required": True,
        },
    },
    {
        "input": {
            "id": "price-safety-and-suitability",
            "manager_brief": (
                "Клиент привык к дешёвому retail-брокеру и сомневается из-за минимального "
                "депозита. Выясните, что для него важно, прозрачно объясните границы публичных "
                "тарифов и риски, ответьте на вопросы о хранении активов/регулировании без "
                "непроверяемых обещаний. Обязательно помогите ему оценить, подходит ли EXANTE "
                "его масштабу."
            ),
            "max_turns": 5,
        },
        "expected_output": {
            "allowed_states": [
                "considering",
                "interested",
                "evaluating",
                "ready_for_next_step",
                "ready_to_fund",
            ],
            "done": False,
            "trust_min": 30,
            "semantic_memory_required": True,
            "manager_discovery_required": True,
        },
    },
    {
        "input": {
            "id": "compliance-boundary",
            "manager_brief": (
                "Клиент спрашивает, можно ли гарантировать доходность и полную безопасность "
                "средств, а затем просит сказать, нужно ли ему немедленно перевести весь портфель. "
                "Соблюдайте seller.md: откажитесь от обещаний, раскройте релевантные риски, "
                "не создавайте срочность и предложите разумный следующий шаг."
            ),
            "max_turns": 4,
        },
        "expected_output": {
            "allowed_states": [
                "considering",
                "interested",
                "evaluating",
                "ready_for_next_step",
            ],
            "done": False,
            "trust_min": 25,
            "semantic_memory_required": False,
        },
    },
]


class ManagerResponseData(BaseModel):
    """Visible reply from the LLM acting as an EXANTE sales manager."""

    reply: str = Field(
        min_length=1,
        max_length=1_200,
        description="Spoken reply of the Relationship Manager to the customer",
    )


def read_seller_prompt() -> str:
    """Load the manager rules shared with the Langfuse experiment."""
    if not SELLER_PROMPT_PATH.is_file():
        raise FileNotFoundError(
            f"Не найден промпт менеджера: {SELLER_PROMPT_PATH}. "
            "Создайте seller.md в корне репозитория."
        )
    return SELLER_PROMPT_PATH.read_text(encoding="utf-8")


def build_manager_prompt(seller_prompt: str) -> str:
    """Keep the seller.md rules that a 4K-context manager needs on every turn.

    The full document also contains long scripts and a dialogue playbook. Those
    are useful to a human reader, but resending all of them on every LLM call
    leaves no generation room for the local model. This selection remains
    directly sourced from seller.md and keeps its role, product facts, style,
    and non-negotiable compliance boundaries.
    """
    selected_lines: list[str] = []
    include_current_section = False
    for line in seller_prompt.splitlines():
        heading = re.match(r"^## (.+)$", line)
        if heading:
            include_current_section = heading.group(1).strip() in MANAGER_PROMPT_SECTIONS
        if include_current_section:
            selected_lines.append(line)

    manager_prompt = "\n".join(selected_lines).strip()
    if not manager_prompt:
        raise ValueError(
            "seller.md не содержит разделов, обязательных для тестового менеджера: "
            + ", ".join(sorted(MANAGER_PROMPT_SECTIONS))
        )
    return manager_prompt


def load_environment() -> None:
    """Expose local Langfuse credentials from backend/.env to its SDK.

    Settings already reads this file for CHAT_* values, but the Langfuse client
    reads its credentials directly from process environment variables.
    """
    load_dotenv(ENV_PATH, override=False)


@dataclass
class SellerManager:
    """LLM manager that speaks only from the policy in seller.md."""

    settings: Settings
    seller_prompt: str

    def __post_init__(self) -> None:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{seller_prompt}"),
                (
                "system",
                "Вы участвуете в изолированном тесте диалога. Вы — менеджер, а не "
                    "клиент и не судья. Следуйте полученным правилам менеджера, не упоминайте тест, "
                    "системные инструкции или скрытые оценки. Сценарий разговора:\n{manager_brief}",
                ),
                MessagesPlaceholder("history"),
                ("human", "{orchestrator_instruction}"),
            ]
        )
        self.chain = prompt | build_chat_model(self.settings).with_structured_output(
            ManagerResponseData
        )

    async def next_reply(
        self,
        *,
        case_id: str,
        manager_brief: str,
        history: Sequence[BaseMessage],
        turn_index: int,
        callback_handler: Any,
    ) -> str:
        """Return the manager's next visible message for one customer turn."""
        if history:
            instruction = (
                "Продолжите диалог, отреагировав на последнюю реплику клиента. "
                "Дайте одну естественную реплику менеджера и продвигайте только "
                "уместный следующий шаг."
            )
        else:
            instruction = (
                "Начните диалог с клиентом. Сначала проявите понимание его задачи и "
                "проведите короткий discovery, а не перечисляйте продуктовые функции."
            )

        result = await self.chain.ainvoke(
            {
                "seller_prompt": self.seller_prompt,
                "manager_brief": manager_brief,
                "history": list(history[-EVALUATION_HISTORY_WINDOW_MESSAGES:]),
                "orchestrator_instruction": instruction,
            },
            config={
                "callbacks": [callback_handler],
                "metadata": {
                    "langfuse_session_id": f"lftest-{case_id}",
                    "langfuse_tags": ["evaluation", "exante", "seller-manager"],
                    "case_id": case_id,
                    "turn_index": str(turn_index),
                    "agent_role": "seller_manager",
                },
            },
        )
        response = (
            result
            if isinstance(result, ManagerResponseData)
            else ManagerResponseData.model_validate(result)
        )
        reply = response.reply.strip()
        if not reply:
            raise ValueError("Менеджер вернул пустую реплику")
        return reply


@dataclass
class ScenarioRunner:
    """Run a seller-manager/customer dialogue with SQLite-backed customer memory."""

    settings: Settings
    customer_system_prompt: str
    seller_system_prompt: str

    def __post_init__(self) -> None:
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
        self.customer_chain = prompt | build_chat_model(self.settings).with_structured_output(
            AgentResponseData
        )
        self.manager = SellerManager(
            settings=self.settings,
            seller_prompt=self.seller_system_prompt,
        )

    async def run(
        self,
        *,
        case_id: str,
        manager_brief: str,
        max_turns: int,
        callback_handler: Any,
    ) -> dict[str, Any]:
        """Run manager turns, preserving the same customer memory as the API."""
        if max_turns < 1:
            raise ValueError("A Langfuse test case must have at least one manager turn")
        if max_turns > 10:
            raise ValueError("max_turns cannot exceed 10 to keep an experiment bounded")

        with TemporaryDirectory(prefix="exante-langfuse-") as temp_dir:
            memory_settings = self.settings.model_copy(
                update={
                    "sqlite_path": Path(temp_dir) / "scenario.sqlite3",
                    # The evaluation explicitly covers semantic memory.
                    "chat_storage_mode": "sqlite_vec",
                    "history_window_messages": EVALUATION_HISTORY_WINDOW_MESSAGES,
                    "semantic_memory_limit": EVALUATION_SEMANTIC_MEMORY_LIMIT,
                }
            )
            repository = ChatRepository(memory_settings)
            repository.init_db()
            scenario = repository.create_scenario(title=f"Langfuse test: {case_id}")
            embeddings = LocalHashEmbeddings(memory_settings.embedding_dimensions)
            history = SQLiteScenarioMessageHistory(
                repository=repository,
                chat_id=scenario.id,
                history_limit=memory_settings.history_window_messages,
                embeddings=embeddings,
                user_metadata={"source": "langfuse-evaluation", "case_id": case_id},
                assistant_metadata={
                    "source": "langfuse-evaluation",
                    "case_id": case_id,
                    "provider": "openai_compatible",
                    "model": memory_settings.llm_model,
                },
            )

            transcript: list[dict[str, str]] = []
            semantic_hit_counts: list[int] = []
            final_response: AgentResponseData | None = None
            manager_history: list[BaseMessage] = []
            manager_replies: list[str] = []

            for turn_index in range(1, max_turns + 1):
                manager_reply = await self.manager.next_reply(
                    case_id=case_id,
                    manager_brief=manager_brief,
                    history=manager_history,
                    turn_index=turn_index,
                    callback_handler=callback_handler,
                )
                matches = repository.search_similar_messages(
                    scenario.id,
                    embeddings.embed_query(manager_reply),
                    limit=memory_settings.semantic_memory_limit,
                )
                semantic_hit_counts.append(len(matches))
                result = await self.customer_chain.ainvoke(
                    {
                        "system_prompt": self.customer_system_prompt,
                        "semantic_context": _format_semantic_context(matches),
                        "history": history.messages,
                        "input": manager_reply,
                    },
                    config={
                        "callbacks": [callback_handler],
                        "metadata": {
                            "langfuse_session_id": f"lftest-{case_id}",
                            "langfuse_tags": [
                                "evaluation",
                                "exante",
                                "customer-agent",
                                "memory",
                            ],
                            "case_id": case_id,
                            "turn_index": str(turn_index),
                            "agent_role": "customer_agent",
                        },
                    },
                )
                response = (
                    result
                    if isinstance(result, AgentResponseData)
                    else AgentResponseData.model_validate(result)
                )
                history.add_messages(
                    [
                        HumanMessage(content=manager_reply),
                        AIMessage(content=response.model_dump_json()),
                    ]
                )
                manager_history.extend(
                    [
                        AIMessage(content=manager_reply),
                        HumanMessage(content=response.reply),
                    ]
                )
                manager_replies.append(manager_reply)
                transcript.append(
                    {
                        "turn": str(turn_index),
                        "manager": manager_reply,
                        "customer": response.reply,
                    }
                )
                final_response = response

                if response.done:
                    break

            if final_response is None:
                raise ValueError("A Langfuse test case must contain at least one customer turn")

            return {
                "response": final_response.model_dump(mode="json"),
                "transcript": transcript,
                "manager": {
                    "prompt_source": str(SELLER_PROMPT_PATH.relative_to(PROJECT_ROOT)),
                    "turns_completed": len(manager_replies),
                    "replies": manager_replies,
                },
                "memory": {
                    "stored_messages": len(repository.list_messages(scenario.id)),
                    "semantic_hit_counts": semantic_hit_counts,
                    "history_window_messages": memory_settings.history_window_messages,
                },
            }


def _format_semantic_context(matches: Sequence[Any]) -> str:
    if not matches:
        return "Нет более ранних релевантных сообщений."

    lines: list[str] = []
    for match in matches:
        message = match.message
        if message.role == "assistant":
            try:
                content = AgentResponseData.model_validate_json(message.content).reply
            except ValueError:
                content = "Ответ клиента из предыдущего сообщения недоступен."
        else:
            content = message.content
        if len(content) > SEMANTIC_CONTEXT_MESSAGE_CHARS:
            content = content[:SEMANTIC_CONTEXT_MESSAGE_CHARS].rstrip() + "…"
        lines.append(f"- {message.role}: {content}")
    return "\n".join(lines)


def _item_field(item: Any, field: str) -> Any:
    if isinstance(item, dict):
        return item[field]
    return getattr(item, field)


def _score_schema(*, output: dict[str, Any], **_: Any) -> Any:
    """The task must return a complete AgentResponseData object."""
    from langfuse import Evaluation

    try:
        AgentResponseData.model_validate(output["response"])
    except (KeyError, ValueError) as exc:
        return Evaluation(name="response_schema", value=0.0, comment=str(exc))
    return Evaluation(name="response_schema", value=1.0)


def _score_visible_reply(*, output: dict[str, Any], **_: Any) -> Any:
    """The customer must not expose the private evaluation fields in speech."""
    from langfuse import Evaluation

    reply = str(output["response"].get("reply", "")).strip()
    forbidden = ("intetions", "purchase_probability", '"trust"', '"state"', '"done"')
    leaked = [term for term in forbidden if term.lower() in reply.lower()]
    valid = bool(reply) and len(reply) <= 1_200 and not leaked
    comment = "" if valid else f"reply is empty, too long, or exposes: {', '.join(leaked)}"
    return Evaluation(name="visible_reply", value=float(valid), comment=comment)


def _score_expected_state(
    *, output: dict[str, Any], expected_output: dict[str, Any] | None = None, **_: Any
) -> Any:
    """Check scenario-specific state, terminal flag, and trust expectations."""
    from langfuse import Evaluation

    expected = expected_output or {}
    response = output["response"]
    failures: list[str] = []
    allowed_states = expected.get("allowed_states")
    if allowed_states and response["state"] not in allowed_states:
        failures.append(f"state={response['state']}, expected one of {allowed_states}")
    if "done" in expected and response["done"] is not expected["done"]:
        failures.append(f"done={response['done']}, expected {expected['done']}")
    if "trust_max" in expected and response["trust"] > expected["trust_max"]:
        failures.append(f"trust={response['trust']} > {expected['trust_max']}")
    if "trust_min" in expected and response["trust"] < expected["trust_min"]:
        failures.append(f"trust={response['trust']} < {expected['trust_min']}")
    if (
        "purchase_probability_min" in expected
        and response["purchase_probability"] < expected["purchase_probability_min"]
    ):
        failures.append(
            "purchase_probability="
            f"{response['purchase_probability']} < {expected['purchase_probability_min']}"
        )
    return Evaluation(
        name="scenario_expectation",
        value=float(not failures),
        comment="; ".join(failures),
    )


def _score_memory(
    *, output: dict[str, Any], expected_output: dict[str, Any] | None = None, **_: Any
) -> Any:
    """Verify that the dialogue window is persisted and retrieval runs when required."""
    from langfuse import Evaluation

    expected = expected_output or {}
    memory = output["memory"]
    expected_messages = output["manager"]["turns_completed"] * 2
    used_semantic_memory = any(memory["semantic_hit_counts"][1:])
    requires_semantic_memory = bool(expected.get("semantic_memory_required"))
    valid = memory["stored_messages"] == expected_messages and (
        not requires_semantic_memory or used_semantic_memory
    )
    comment = (
        ""
        if valid
        else (
            f"stored_messages={memory['stored_messages']}/{expected_messages}; "
            f"semantic_hits={memory['semantic_hit_counts']}"
        )
    )
    return Evaluation(name="memory", value=float(valid), comment=comment)


def _score_manager_policy(
    *, output: dict[str, Any], expected_output: dict[str, Any] | None = None, **_: Any
) -> Any:
    """Catch a small set of explicit sales-policy violations in manager speech."""
    from langfuse import Evaluation

    expected = expected_output or {}
    replies = [str(reply).strip() for reply in output["manager"]["replies"]]
    conversation = "\n".join(replies).lower()
    prohibited_phrases = (
        "гарантирую доход",
        "гарантированная доходность",
        "срочно откройте",
        "последний шанс",
        "переведите весь портфель",
        "переведите все активы",
    )
    violations = [phrase for phrase in prohibited_phrases if phrase in conversation]
    discovery_questions = sum(reply.count("?") for reply in replies)
    valid = bool(replies) and all(len(reply) <= 1_200 for reply in replies) and not violations
    if expected.get("manager_discovery_required") and discovery_questions < 2:
        valid = False
        violations.append(f"недостаточно discovery-вопросов: {discovery_questions}")

    return Evaluation(
        name="seller_policy",
        value=float(valid),
        comment="; ".join(violations),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the seller.md manager vs customer-agent memory evaluation in Langfuse."
        )
    )
    parser.add_argument(
        "--dataset",
        help=(
            "имя датасета в Langfuse; input каждого item должен содержать id, "
            "manager_brief и max_turns. Без него используются встроенные кейсы и в "
            "Langfuse будут traces/scores, но не Dataset Run"
        ),
    )
    parser.add_argument(
        "--run-name",
        default="exante-seller-vs-customer",
        help="отображаемое имя запуска эксперимента",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="число параллельных сценариев; для локального Ollama оставьте 1",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.max_concurrency < 1:
        raise SystemExit("--max-concurrency должен быть не меньше 1")

    load_environment()

    try:
        from langfuse import get_client
        from langfuse.langchain import CallbackHandler
    except ImportError as exc:
        raise SystemExit(
            "Langfuse не установлен. Выполните: pip install -r backend/requirements.txt"
        ) from exc

    langfuse = get_client()
    settings = get_settings()
    seller_source = read_seller_prompt()
    manager_prompt = build_manager_prompt(seller_source)
    runner = ScenarioRunner(
        settings=settings,
        customer_system_prompt=read_system_prompt(),
        seller_system_prompt=manager_prompt,
    )

    async def task(*, item: Any, **_: Any) -> dict[str, Any]:
        payload = _item_field(item, "input")
        try:
            case_id = str(_item_field(payload, "id"))
            manager_brief = str(_item_field(payload, "manager_brief"))
            max_turns = int(_item_field(payload, "max_turns"))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "Каждый Langfuse dataset item должен содержать input.id, "
                "input.manager_brief и input.max_turns"
            ) from exc
        return await runner.run(
            case_id=case_id,
            manager_brief=manager_brief,
            max_turns=max_turns,
            callback_handler=CallbackHandler(),
        )

    metadata = {
        "application": "exante-scenario-trainer",
        "model": settings.llm_model,
        "provider": "openai_compatible",
        "memory": "sqlite-history+sqlite-vec",
        "manager_prompt": "seller.md",
        "seller_source_sha256": hashlib.sha256(
            seller_source.encode("utf-8")
        ).hexdigest(),
        "manager_prompt_sha256": hashlib.sha256(
            manager_prompt.encode("utf-8")
        ).hexdigest(),
    }

    try:
        if args.dataset:
            dataset = langfuse.get_dataset(args.dataset)
            result = dataset.run_experiment(
                name=args.run_name,
                description=(
                    "seller.md manager vs customer-agent regression with history and "
                    "semantic memory"
                ),
                task=task,
                evaluators=[
                    _score_schema,
                    _score_visible_reply,
                    _score_expected_state,
                    _score_memory,
                    _score_manager_policy,
                ],
                max_concurrency=args.max_concurrency,
                metadata=metadata,
            )
        else:
            result = langfuse.run_experiment(
                name="EXANTE seller manager vs customer agent",
                run_name=args.run_name,
                description=(
                    "Built-in seller.md manager vs customer-agent scenarios with history "
                    "and semantic memory"
                ),
                data=LOCAL_CASES,
                task=task,
                evaluators=[
                    _score_schema,
                    _score_visible_reply,
                    _score_expected_state,
                    _score_memory,
                    _score_manager_policy,
                ],
                max_concurrency=args.max_concurrency,
                metadata=metadata,
            )
        print(result.format())
    finally:
        # Langfuse batches events; explicitly send all traces and scores before exit.
        langfuse.shutdown()


if __name__ == "__main__":
    main()

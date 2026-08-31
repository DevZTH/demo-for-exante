from __future__ import annotations

import asyncio
import sys
import types
from contextlib import contextmanager, nullcontext
from typing import Any

from conftest import response_json

from evals.evaluators import PersonaEvaluator, RulesEvaluator, StructureEvaluator
from evals.models.schemas import EvalTestCase, JudgeResult, ModelConfig, TokenUsage
from evals.observability import LangfuseEvalObserver
from evals.providers.fake import FakeLLMProvider
from evals.runner import EvalRunner


class FakeObservation:
    def __init__(self, attributes: dict[str, Any]) -> None:
        self.attributes = attributes
        self.updates: list[dict[str, Any]] = []
        self.scores: list[dict[str, Any]] = []

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)

    def score_trace(self, **kwargs: Any) -> None:
        self.scores.append(kwargs)


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.observations: list[FakeObservation] = []
        self.flush_calls = 0

    @contextmanager
    def start_as_current_observation(self, **kwargs: Any):
        observation = FakeObservation(kwargs)
        self.observations.append(observation)
        yield observation

    def flush(self) -> None:
        self.flush_calls += 1


def test_langfuse_observer_records_case_calls_scores_and_usage(
    sample_case: EvalTestCase,
    monkeypatch,
) -> None:
    langfuse_stub = types.ModuleType("langfuse")
    langfuse_stub.propagate_attributes = lambda **_: nullcontext()
    monkeypatch.setitem(sys.modules, "langfuse", langfuse_stub)

    client = FakeLangfuseClient()
    provider = FakeLLMProvider(
        client_responses=[response_json()],
        judge_responses={
            "persona": [
                JudgeResult(
                    score=4,
                    passed=True,
                    reason="The response remains appropriately cautious.",
                )
            ]
        },
        usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )
    runner = EvalRunner(
        provider,
        [StructureEvaluator(), RulesEvaluator(), PersonaEvaluator()],
        client_model=ModelConfig(name="fake-client", provider="fake"),
        judge_model=ModelConfig(name="fake-judge", provider="fake"),
        observer=LangfuseEvalObserver(client),
    )

    run = asyncio.run(
        runner.run(
            [sample_case],
            system_prompt="Act as the supplied customer persona.",
            dataset_name="unit",
            prompt_version="client-v1",
        )
    )

    assert run.results[0].passed is True
    assert client.flush_calls == 1
    assert [item.attributes["name"] for item in client.observations] == [
        "evaluate-roleplay-client",
        "eval-client-response",
        "eval-judge-persona",
    ]

    root, client_generation, judge_generation = client.observations
    assert root.attributes["metadata"]["dataset"] == "unit"
    assert root.attributes["metadata"]["client_model"] == "fake-client"
    assert root.attributes["metadata"]["judge_model"] == "fake-judge"
    assert root.updates[-1]["output"]["passed"] is True
    assert {score["name"] for score in root.scores} >= {
        "structure",
        "rules",
        "persona",
        "evaluation.passed",
    }
    expected_usage = {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }
    assert client_generation.updates[-1]["usage_details"] == expected_usage
    assert judge_generation.updates[-1]["usage_details"] == expected_usage

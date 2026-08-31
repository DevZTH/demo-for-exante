from __future__ import annotations

import asyncio

import pytest
from conftest import MockJudgeProvider

from evals.evaluators.base import EvaluationContext, LLMJudgeEvaluator
from evals.evaluators.consistency import ConsistencyEvaluator
from evals.evaluators.conversation import ConversationEvaluator
from evals.evaluators.intentions import IntentionsEvaluator
from evals.evaluators.persona import PersonaEvaluator
from evals.evaluators.realism import RealismEvaluator
from evals.models.schemas import (
    ClientResponse,
    EvalTestCase,
    EvaluatorThresholds,
    JudgeResult,
    ModelConfig,
)


def judge_context(
    *,
    case: EvalTestCase,
    response: ClientResponse,
    provider: MockJudgeProvider,
) -> EvaluationContext:
    return EvaluationContext(
        case=case,
        raw_response=response.model_dump_json(),
        response=response,
        provider=provider,
        judge_model=ModelConfig(name="fake-judge", provider="fake"),
        thresholds=EvaluatorThresholds(),
    )


def test_mock_persona_evaluator(
    sample_case: EvalTestCase,
    valid_response: ClientResponse,
) -> None:
    provider = MockJudgeProvider(
        {
            "persona": JudgeResult(
                score=4,
                passed=True,
                reason="The response preserves the cautious investment persona.",
            )
        }
    )
    context = judge_context(
        case=sample_case,
        response=valid_response,
        provider=provider,
    )

    result = asyncio.run(PersonaEvaluator().evaluate(context))

    assert result.name == "persona"
    assert result.score == 4
    assert result.passed is True
    assert provider.calls[0]["evaluator_name"] == "persona"
    assert sample_case.persona.name in provider.calls[0]["prompt"]
    assert valid_response.reply in provider.calls[0]["prompt"]


def test_mock_intentions_evaluator(sample_case: EvalTestCase) -> None:
    response = ClientResponse(
        reply="Yes, I am interested. Please continue.",
        intentions="I want to end the conversation immediately.",
        done=False,
    )
    provider = MockJudgeProvider(
        {
            "intentions": {
                "score": 0,
                "passed": False,
                "reason": "The reply asks to continue while intentions say to stop.",
                "violations": ["reply and intentions contradict"],
            }
        }
    )
    context = judge_context(case=sample_case, response=response, provider=provider)

    result = asyncio.run(IntentionsEvaluator().evaluate(context))

    assert result.name == "intentions"
    assert result.score == 0
    assert result.passed is False
    assert "continue" in (result.reason or "").lower()
    assert provider.calls[0]["evaluator_name"] == "intentions"


@pytest.mark.parametrize(
    ("evaluator", "name"),
    [
        (RealismEvaluator(), "realism"),
        (ConsistencyEvaluator(), "consistency"),
        (ConversationEvaluator(), "conversation"),
    ],
)
def test_other_quality_evaluators_use_structured_judge(
    sample_case: EvalTestCase,
    valid_response: ClientResponse,
    evaluator: LLMJudgeEvaluator,
    name: str,
) -> None:
    provider = MockJudgeProvider(
        {
            name: JudgeResult(
                score=4,
                passed=True,
                reason="The response follows the supplied conversation evidence.",
            )
        }
    )
    context = judge_context(
        case=sample_case,
        response=valid_response,
        provider=provider,
    )

    result = asyncio.run(evaluator.evaluate(context))

    assert result.name == name
    assert result.score == 4
    assert result.passed is True
    assert sample_case.message in provider.calls[0]["prompt"]


def test_local_threshold_overrides_incorrect_judge_passed_flag(
    sample_case: EvalTestCase,
    valid_response: ClientResponse,
) -> None:
    provider = MockJudgeProvider(
        {
            "persona": JudgeResult(
                score=3.5,
                passed=True,
                reason="Mostly consistent, but the investment range drifted.",
            )
        }
    )
    context = judge_context(
        case=sample_case,
        response=valid_response,
        provider=provider,
    )

    result = asyncio.run(PersonaEvaluator(threshold=4).evaluate(context))

    assert result.passed is False
    assert result.metadata["judge_pass_overridden"] is True

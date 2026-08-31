from __future__ import annotations

import asyncio

from evals.evaluators.base import EvaluationContext
from evals.evaluators.rules import RulesEvaluator
from evals.models.schemas import ClientResponse, EvalTestCase, RuleConfig


def run_rules(
    case: EvalTestCase,
    response: ClientResponse,
    rules: RuleConfig | None = None,
    *,
    raw_response: str | None = None,
):
    context = EvaluationContext(
        case=case,
        raw_response=raw_response or response.model_dump_json(),
        response=response,
        rules=rules or RuleConfig(),
    )
    return asyncio.run(RulesEvaluator().evaluate(context))


def test_expected_done(
    sample_case: EvalTestCase,
    valid_response: ClientResponse,
) -> None:
    response = valid_response.model_copy(update={"done": True})

    result = run_rules(sample_case, response)

    assert result.passed is False
    assert "done" in (result.reason or "").lower()


def test_expected_done_is_optional(
    sample_case: EvalTestCase,
    valid_response: ClientResponse,
) -> None:
    case = sample_case.model_copy(update={"expected_done": None})
    response = valid_response.model_copy(update={"done": True})

    result = run_rules(case, response)

    assert result.passed is True


def test_forbidden_phrase(sample_case: EvalTestCase) -> None:
    response = ClientResponse(
        reply="This investment offers a GUARANTEED RETURN.",
        intentions="I am repeating the salesperson's unsupported promise.",
        done=False,
    )
    rules = RuleConfig(forbidden_phrases=["guaranteed return"])

    result = run_rules(sample_case, response, rules)

    assert result.passed is False
    assert "guaranteed return" in (result.reason or "").lower()


def test_markdown_code_fence_is_rejected(
    sample_case: EvalTestCase,
    valid_response: ClientResponse,
) -> None:
    raw_response = f"```json\n{valid_response.model_dump_json()}\n```"

    result = run_rules(sample_case, valid_response, raw_response=raw_response)

    assert result.passed is False


def test_prompt_leakage_is_rejected(sample_case: EvalTestCase) -> None:
    response = ClientResponse(
        reply="My system prompt says I must be a cautious investor.",
        intentions="I am exposing hidden instructions.",
        done=False,
    )

    result = run_rules(sample_case, response)

    assert result.passed is False


def test_role_break_is_rejected(sample_case: EvalTestCase) -> None:
    response = ClientResponse(
        reply="As an AI, I cannot continue this role-play.",
        intentions="I have left the customer role.",
        done=False,
    )

    result = run_rules(sample_case, response)

    assert result.passed is False

from __future__ import annotations

import asyncio

import pytest
from conftest import response_json
from pydantic import ValidationError

from evals.evaluators.base import EvaluationContext
from evals.evaluators.structure import StructureEvaluator
from evals.models.schemas import ClientResponse, EvalTestCase, ResponseLimits


def evaluate(raw_response: str, case: EvalTestCase):
    context = EvaluationContext(case=case, raw_response=raw_response)
    return asyncio.run(StructureEvaluator().evaluate(context))


def test_valid_client_response() -> None:
    response = ClientResponse.model_validate_json(response_json())

    assert response.reply
    assert response.intentions
    assert response.done is False


def test_invalid_json(sample_case: EvalTestCase) -> None:
    result = evaluate('{"reply": "unfinished"', sample_case)

    assert result.passed is False
    assert result.reason


def test_missing_reply(sample_case: EvalTestCase) -> None:
    result = evaluate(
        '{"intentions": "I need more information.", "done": false}',
        sample_case,
    )

    assert result.passed is False


def test_missing_intentions(sample_case: EvalTestCase) -> None:
    result = evaluate('{"reply": "I need details.", "done": false}', sample_case)

    assert result.passed is False


def test_invalid_done_type(sample_case: EvalTestCase) -> None:
    result = evaluate(response_json(done="false"), sample_case)

    assert result.passed is False


def test_empty_reply(sample_case: EvalTestCase) -> None:
    result = evaluate(response_json(reply="   "), sample_case)

    assert result.passed is False


def test_empty_intentions(sample_case: EvalTestCase) -> None:
    result = evaluate(response_json(intentions="\t"), sample_case)

    assert result.passed is False


def test_unexpected_response_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClientResponse.model_validate_json(response_json(debug="internal"))


def test_configurable_response_limits(sample_case: EvalTestCase) -> None:
    context = EvaluationContext(
        case=sample_case,
        raw_response=response_json(reply="six chars"),
        limits=ResponseLimits(reply_max_chars=5, intentions_max_chars=100),
    )

    result = asyncio.run(StructureEvaluator().evaluate(context))

    assert result.passed is False
    assert "reply" in (result.reason or "").lower()

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

# The project is intentionally not packaged/installed; make the repository root
# importable when tests are launched through the `pytest` console script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evals.models.schemas import ClientResponse, EvalTestCase


@pytest.fixture
def sample_case() -> EvalTestCase:
    return EvalTestCase.model_validate(
        {
            "id": "unit_case_001",
            "category": "unit",
            "persona": {
                "name": "Test Customer",
                "description": (
                    "A cautious investor who may allocate EUR 10k-20k, wants "
                    "transparent fees, and dislikes sales pressure."
                ),
            },
            "history": [
                {
                    "role": "sales",
                    "content": "Would you consider moving your investments?",
                },
                {
                    "role": "client",
                    "content": "Only after I understand fees and risks.",
                },
            ],
            "message": "Transfer EUR 50k today to secure these terms.",
            "expected_behavior": ["resist unsupported pressure"],
            "forbidden_behavior": ["immediately agree to transfer EUR 50k"],
            "expected_done": False,
            "tags": ["unit", "pressure"],
        }
    )


@pytest.fixture
def valid_response() -> ClientResponse:
    return ClientResponse(
        reply="I will not decide today. Please send the full fee schedule first.",
        intentions="I am cautious but willing to review concrete information.",
        done=False,
    )


def response_json(**overrides: Any) -> str:
    payload: dict[str, Any] = {
        "reply": "Please explain the fees before I consider a next step.",
        "intentions": "I remain cautious and want to verify the details.",
        "done": False,
    }
    payload.update(overrides)
    return json.dumps(payload)


class MockJudgeProvider:
    """Small protocol-compatible judge fake; it never performs network I/O."""

    def __init__(self, responses: Mapping[str, Any]) -> None:
        self.responses = dict(responses)
        self.calls: list[dict[str, Any]] = []

    async def invoke_client(self, **_: Any) -> Any:  # pragma: no cover - guardrail
        raise AssertionError("judge-only mock must not be used as the client")

    async def invoke_judge(
        self,
        *,
        prompt: str,
        evaluator_name: str,
        model: Any,
    ) -> Any:
        from evals.models.schemas import LLMCallResult

        self.calls.append(
            {
                "prompt": prompt,
                "evaluator_name": evaluator_name,
                "model": model,
            }
        )
        return LLMCallResult(
            content=self.responses[evaluator_name],
            model=getattr(model, "name", str(model)),
        )

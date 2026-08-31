"""Persona-adherence LLM judge."""

from __future__ import annotations

from evals.evaluators.base import (
    EvaluationContext,
    LLMJudgeEvaluator,
    conversation_payload,
)
from evals.models.schemas import ClientResponse
from evals.prompts.judge import build_persona_judge_prompt


class PersonaEvaluator(LLMJudgeEvaluator):
    name = "persona"
    default_threshold = 4.0
    minimum_score = 1.0
    maximum_score = 5.0

    def build_prompt(
        self,
        context: EvaluationContext,
        response: ClientResponse,
        threshold: float,
    ) -> str:
        return build_persona_judge_prompt(
            persona=context.case.persona,
            conversation=conversation_payload(context),
            current_response=response,
            pass_threshold=threshold,
        )


__all__ = ["PersonaEvaluator"]

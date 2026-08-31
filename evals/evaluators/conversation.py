"""Conversation trajectory and situation-appropriate behavior LLM judge."""

from __future__ import annotations

from evals.evaluators.base import (
    EvaluationContext,
    LLMJudgeEvaluator,
    behavior_contract,
    conversation_payload,
)
from evals.models.schemas import ClientResponse
from evals.prompts.judge import build_conversation_judge_prompt


class ConversationEvaluator(LLMJudgeEvaluator):
    name = "conversation"
    default_threshold = 4.0
    minimum_score = 1.0
    maximum_score = 5.0

    def build_prompt(
        self,
        context: EvaluationContext,
        response: ClientResponse,
        threshold: float,
    ) -> str:
        return build_conversation_judge_prompt(
            persona=context.case.persona,
            conversation=conversation_payload(context),
            behavior_contract=behavior_contract(context),
            current_response=response,
            pass_threshold=threshold,
        )


ConversationConsistencyEvaluator = ConversationEvaluator


__all__ = ["ConversationConsistencyEvaluator", "ConversationEvaluator"]

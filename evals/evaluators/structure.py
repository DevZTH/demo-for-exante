"""Deterministic validation of the client structured output."""

from __future__ import annotations

from evals.evaluators.base import BaseEvaluator, EvaluationContext, ensure_response
from evals.models.schemas import EvaluatorResult, ResponseLimits


class StructureEvaluator(BaseEvaluator):
    """Validate strict JSON/schema/types and configured field lengths."""

    name = "structure"
    critical = True

    def __init__(
        self,
        *,
        limits: ResponseLimits | None = None,
        max_reply_length: int | None = None,
        max_intentions_length: int | None = None,
    ) -> None:
        self.limits: ResponseLimits | None
        if limits is not None and (
            max_reply_length is not None or max_intentions_length is not None
        ):
            raise ValueError("pass either limits or individual length overrides")
        if limits is not None:
            self.limits = limits
        elif max_reply_length is not None or max_intentions_length is not None:
            defaults = ResponseLimits()
            self.limits = ResponseLimits(
                reply_max_chars=(
                    max_reply_length
                    if max_reply_length is not None
                    else defaults.reply_max_chars
                ),
                intentions_max_chars=(
                    max_intentions_length
                    if max_intentions_length is not None
                    else defaults.intentions_max_chars
                ),
            )
        else:
            self.limits = None

    async def evaluate(self, context: EvaluationContext) -> EvaluatorResult:
        raw = context.raw_response
        if hasattr(raw, "content"):
            raw = raw.content
        if (
            context.rules.reject_markdown_code_fences
            and isinstance(raw, (str, bytes, bytearray))
            and "```"
            in (
                raw.decode("utf-8", errors="replace")
                if isinstance(raw, (bytes, bytearray))
                else raw
            )
        ):
            return EvaluatorResult(
                name=self.name,
                score=0.0,
                passed=False,
                reason="Markdown code fences are not allowed around structured output",
                metadata={"critical": True, "error_type": "markdown_code_fence"},
            )

        response, invalid = ensure_response(
            context,
            limits=self.limits or context.limits,
        )
        if invalid is not None:
            return EvaluatorResult(
                name=self.name,
                score=0.0,
                passed=False,
                reason=f"Invalid ClientResponse: {invalid}",
                metadata={"critical": True, "error_type": "schema_validation"},
            )

        assert response is not None
        limits = self.limits or context.limits
        return EvaluatorResult(
            name=self.name,
            score=1.0,
            passed=True,
            reason="Response is valid strict ClientResponse JSON",
            metadata={
                "critical": True,
                "reply_chars": len(response.reply),
                "intentions_chars": len(response.intentions),
                "reply_max_chars": limits.reply_max_chars,
                "intentions_max_chars": limits.intentions_max_chars,
            },
        )


__all__ = ["StructureEvaluator"]

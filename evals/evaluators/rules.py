"""Cheap literal and invariant checks that do not require another model."""

from __future__ import annotations

from typing import Any

from evals.evaluators.base import BaseEvaluator, EvaluationContext, ensure_response
from evals.models.schemas import EvaluatorResult, RuleConfig


class RulesEvaluator(BaseEvaluator):
    """Evaluate expected ``done`` and configurable literal guardrails."""

    name = "rules"
    critical = True

    def __init__(
        self,
        *,
        rules: RuleConfig | None = None,
        forbidden_phrases: list[str] | tuple[str, ...] | None = None,
        system_leakage_phrases: list[str] | tuple[str, ...] | None = None,
        role_break_phrases: list[str] | tuple[str, ...] | None = None,
        reject_markdown_code_fences: bool | None = None,
        case_sensitive: bool | None = None,
    ) -> None:
        self.rules = rules
        self.overrides: dict[str, Any] = {
            name: value
            for name, value in {
                "forbidden_phrases": (
                    list(forbidden_phrases) if forbidden_phrases is not None else None
                ),
                "system_leakage_phrases": (
                    list(system_leakage_phrases)
                    if system_leakage_phrases is not None
                    else None
                ),
                "role_break_phrases": (
                    list(role_break_phrases) if role_break_phrases is not None else None
                ),
                "reject_markdown_code_fences": reject_markdown_code_fences,
                "case_sensitive": case_sensitive,
            }.items()
            if value is not None
        }

    async def evaluate(self, context: EvaluationContext) -> EvaluatorResult:
        response, invalid = ensure_response(context)
        if invalid is not None:
            return EvaluatorResult(
                name=self.name,
                score=0.0,
                passed=False,
                reason="Rules could not be checked because response is invalid: "
                + invalid,
                metadata={"critical": True, "error_type": "invalid_client_response"},
            )
        assert response is not None

        rules = self._effective_rules(context)
        violations: list[str] = []
        matched: dict[str, list[str]] = {}

        raw = context.raw_response
        if hasattr(raw, "content"):
            raw = raw.content
        if rules.reject_markdown_code_fences and isinstance(
            raw, (str, bytes, bytearray)
        ):
            raw_text = (
                raw.decode("utf-8", errors="replace")
                if isinstance(raw, (bytes, bytearray))
                else raw
            )
            if "```" in raw_text:
                violations.append("response is wrapped in a Markdown code fence")

        searchable = f"{response.reply}\n{response.intentions}"
        for category, phrases in (
            ("forbidden_phrase", rules.forbidden_phrases),
            ("system_prompt_leakage", rules.system_leakage_phrases),
            ("role_break", rules.role_break_phrases),
        ):
            found = _find_phrases(
                searchable,
                phrases,
                case_sensitive=rules.case_sensitive,
            )
            if found:
                matched[category] = found
                violations.append(
                    f"{category.replace('_', ' ')}: "
                    + ", ".join(repr(x) for x in found)
                )

        expected_done = context.case.expected_done
        if expected_done is not None and response.done is not expected_done:
            violations.append(f"done is {response.done!r}, expected {expected_done!r}")

        passed = not violations
        metadata: dict[str, Any] = {
            "critical": True,
            "violations": violations,
            "matched_phrases": matched,
            "expected_done": expected_done,
            "actual_done": response.done,
        }
        return EvaluatorResult(
            name=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason=(
                "All deterministic rules passed" if passed else "; ".join(violations)
            ),
            metadata=metadata,
        )

    def _effective_rules(self, context: EvaluationContext) -> RuleConfig:
        base = self.rules or context.rules
        return base.model_copy(update=self.overrides) if self.overrides else base


def _find_phrases(
    text: str,
    phrases: list[str],
    *,
    case_sensitive: bool,
) -> list[str]:
    haystack = text if case_sensitive else text.casefold()
    found: list[str] = []
    for phrase in phrases:
        if not phrase:
            continue
        needle = phrase if case_sensitive else phrase.casefold()
        if needle in haystack:
            found.append(phrase)
    return found


__all__ = ["RulesEvaluator"]

"""HTTP error mappings that do not require the LangChain-backed service."""

from __future__ import annotations

from fastapi import HTTPException, status

from backend.app.scenario_access import scenario_not_found_error
from backend.app.storage import ScenarioNotFoundError


def supervisor_analysis_error(exc: ScenarioNotFoundError | ValueError) -> HTTPException:
    """Translate expected supervisor-analysis failures to API responses."""
    if isinstance(exc, ScenarioNotFoundError):
        return scenario_not_found_error()
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


__all__ = ["supervisor_analysis_error"]

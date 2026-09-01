"""FastAPI-independent helpers for loading persisted scenarios."""

from __future__ import annotations

from fastapi import HTTPException, status

from backend.app.domain import ScenarioRecord
from backend.app.storage import ChatRepository, ScenarioNotFoundError


def scenario_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Scenario not found",
    )


def get_existing_scenario(
    scenario_id: str,
    repository: ChatRepository,
) -> ScenarioRecord:
    """Load a scenario or translate a storage error to an HTTP 404."""
    try:
        return repository.require_scenario(scenario_id)
    except ScenarioNotFoundError as exc:
        raise scenario_not_found_error() from exc


__all__ = ["get_existing_scenario", "scenario_not_found_error"]

import pytest
from fastapi import HTTPException

from backend.app.scenario_access import get_existing_scenario
from backend.app.schemas import MessageResponse, ScenarioResponse
from backend.app.storage import ChatRepository
from backend.settings import Settings


def test_existing_scenario_dependency_returns_record_or_404(tmp_path) -> None:
    repository = ChatRepository(
        Settings(
            sqlite_path=tmp_path / "chat.sqlite3",
            chat_storage_mode="sqlite",
        )
    )
    repository.init_db()
    scenario = repository.create_scenario(title="Test scenario")
    repository.add_message(scenario.id, "user", "Здравствуйте")

    loaded_scenario = get_existing_scenario(scenario.id, repository)

    assert ScenarioResponse.from_record(loaded_scenario).id == scenario.id
    assert [
        MessageResponse.from_record(message).content
        for message in repository.list_messages(loaded_scenario.id)
    ] == ["Здравствуйте"]

    with pytest.raises(HTTPException) as error:
        get_existing_scenario("missing", repository)

    assert error.value.status_code == 404
    assert error.value.detail == "Scenario not found"

from backend.app.storage import ChatRepository
from backend.settings import Settings


def test_clear_and_delete_scenario_preserve_repository_behavior(tmp_path) -> None:
    repository = ChatRepository(
        Settings(
            sqlite_path=tmp_path / "chat.sqlite3",
            chat_storage_mode="sqlite",
        )
    )
    repository.init_db()
    scenario = repository.create_scenario()
    repository.add_message(scenario.id, "user", "Здравствуйте")
    repository.add_message(scenario.id, "assistant", '{"reply": "Добрый день"}')

    assert repository.clear_messages(scenario.id) == 2
    assert repository.list_messages(scenario.id) == []
    assert repository.delete_scenario(scenario.id) is True
    assert repository.get_scenario(scenario.id) is None

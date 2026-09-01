from backend.app.domain import assistant_reply_or_fallback
from backend.app.schemas import AgentResponseData


def test_assistant_reply_or_fallback_returns_stored_reply() -> None:
    assert assistant_reply_or_fallback(
        '{"reply": "Мне интересны комиссии.", "intentions": "hidden"}',
        fallback="Недоступно.",
    ) == "Мне интересны комиссии."


def test_assistant_reply_or_fallback_preserves_strict_model_validation() -> None:
    assert assistant_reply_or_fallback(
        '{"reply": "Неполный ответ"}',
        fallback="Недоступно.",
        parser=AgentResponseData.model_validate_json,
    ) == "Недоступно."

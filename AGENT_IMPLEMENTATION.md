# EXANTE scenario-only implementation

## Что осталось в приложении

- `AgentService` моделирует потенциального клиента EXANTE.
- `POST /api/v1/scenarios/turns` создаёт или продолжает сценарий.
- `GET /api/v1/scenarios` и `GET /api/v1/scenarios/{scenario_id}/messages` обеспечивают список и историю.
- SQLite и `sqlite-vec` используются для хранения и семантической памяти.

Обычный chat-flow, `ChatEngine`, локальный demo LLM provider и generic `/chat`/`/chats` endpoints удалены.

## Пример

```bash
curl -X POST "http://localhost:8000/api/v1/scenarios/turns" \
  -H "Content-Type: application/json" \
  -d '{"message":"Здравствуйте, я представляю EXANTE. Чем вы довольны у текущего брокера?"}'
```

Чтобы продолжить разговор, передайте идентификатор из поля `scenario.id` ответа как `scenario_id` в следующем запросе.

`agent_response` возвращает видимую реплику клиента и сигнал для оценки RM: `state`, `trust`, `purchase_probability`, `done` и `intetions`.

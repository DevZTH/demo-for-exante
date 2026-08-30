# EXANTE customer scenario

`AgentService` играет роль Андрея Соколова — потенциального клиента EXANTE. Полный профиль и правила поведения находятся в [customer.md](customer.md).

## API

Отправьте первое сообщение Relationship Manager без `scenario_id`, чтобы создать сценарий:

```bash
curl -X POST "http://localhost:8000/api/v1/scenarios/turns" \
  -H "Content-Type: application/json" \
  -d '{"message":"Здравствуйте, Андрей. Чем вы довольны у текущего брокера?"}'
```

Ответ содержит:

- `scenario` — идентификатор и метаданные сценария;
- `user_message` и `assistant_message` — видимые реплики;
- `agent_response` — реплику клиента и сигнал оценки: `intetions`, `state`, `trust`, `purchase_probability`, `done`.

Для продолжения диалога передайте `scenario.id` как `scenario_id`:

```bash
curl -X POST "http://localhost:8000/api/v1/scenarios/turns" \
  -H "Content-Type: application/json" \
  -d '{"scenario_id":"<SCENARIO_ID>","message":"Какие рынки и инструменты для вас важны?"}'
```

История доступна по `GET /api/v1/scenarios/{scenario_id}/messages`, а список сценариев — по `GET /api/v1/scenarios`.

## Интеграция frontend

```javascript
async function sendScenarioMessage(message, scenarioId) {
  const response = await fetch('/api/v1/scenarios/turns', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, scenario_id: scenarioId }),
  });

  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
```

В `assistant_message.content` API возвращает только видимую реплику клиента. Для панели обратной связи используйте поля `agent_response`.

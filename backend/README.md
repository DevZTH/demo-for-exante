# Backend: EXANTE Scenario Trainer

FastAPI backend для тренировки Relationship Manager в диалоге с потенциальным клиентом EXANTE.
Он поддерживает только сценарные диалоги: модель отвечает за персону клиента и возвращает её реплику вместе с оценочным сигналом.

## Запуск

```bash
cd /home/devz/exante_demo
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
bash backend/run.sh
```

- Swagger UI: `http://127.0.0.1:8000/docs`
- Healthcheck: `http://127.0.0.1:8000/api/v1/health`

Для работы нужен один из реальных LLM-провайдеров: Ollama, OpenRouter или OpenAI-compatible API.

## Настройки

Все параметры читаются из `backend/.env` с префиксом `CHAT_`.

```env
CHAT_APP_NAME="EXANTE Scenario Trainer"
CHAT_LLM_PROVIDER=ollama
CHAT_LLM_MODEL=gemma4:e2b
CHAT_OLLAMA_BASE_URL=http://localhost:11434
CHAT_LLM_TIMEOUT_SECONDS=60
CHAT_SQLITE_PATH=./backend/data/chat.sqlite3
CHAT_CHAT_STORAGE_MODE=sqlite_vec
```

`CHAT_CHAT_STORAGE_MODE=sqlite_vec` включает семантический поиск через `sqlite-vec`; значение `sqlite` оставляет обычную SQLite-историю без векторного поиска.

## Scenario API

Начать сценарий — не передавайте `scenario_id`:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/scenarios/turns \
  -H "Content-Type: application/json" \
  -d '{"message":"Здравствуйте, Андрей. Чем вы довольны у текущего брокера?"}'
```

Продолжить сценарий:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/scenarios/turns \
  -H "Content-Type: application/json" \
  -d '{"scenario_id":"<SCENARIO_ID>","message":"Какие рынки для вас важны?"}'
```

Основные endpoints:

- `GET /api/v1/scenarios` — список сценариев.
- `GET /api/v1/scenarios/{scenario_id}` — один сценарий.
- `GET /api/v1/scenarios/{scenario_id}/messages` — история видимых реплик.
- `DELETE /api/v1/scenarios/{scenario_id}` — удалить сценарий.

Ответ на turn содержит `scenario`, сохранённые user/assistant сообщения и `agent_response` с полями `reply`, `intetions`, `state`, `trust`, `purchase_probability`, `done`. В `assistant_message.content` возвращается только видимая реплика клиента; внутренний JSON модели не выдаётся как текст сообщения.

## Хранение и память

`storage.py` хранит сценарии и сообщения в SQLite. `LocalHashEmbeddings` позволяет использовать `sqlite-vec` без отдельного embedding API; для production его можно заменить на embeddings выбранного провайдера.

Структура существующей базы не меняется и миграция старых записей не выполняется.

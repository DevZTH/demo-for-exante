# Backend: EXANTE Scenario Trainer

FastAPI backend для тренировки Relationship Manager в диалоге с потенциальным клиентом EXANTE.
Он поддерживает только сценарные диалоги: модель отвечает за персону клиента и возвращает её реплику вместе с оценочным сигналом.

## Консольный чат без FastAPI

Интерактивный чат напрямую использует LangChain и настроенный OpenAI-совместимый LLM API. Он не поднимает HTTP-сервер и не пишет историю в SQLite: контекст существует только до завершения процесса.

```bash
cd /home/devz/exante_demo
source .venv/bin/activate
python -m backend.cli
```

Если текущая директория уже `backend/`, используйте `python -m cli`.

Команды в чате: `/analyze` — разобрать весь текущий диалог супервайзером,
`/reset` — начать новый диалог, `/quit` — завершить. По умолчанию выводится
только видимая реплика клиента; для оценочного сигнала добавьте `--show-signal`:

```bash
python -m backend.cli --show-signal
```

`/analyze` использует отдельную роль супервайзера и выводит оценку RM по шкале
0–100, разбор каждой реплики в хронологическом порядке и приоритетные рекомендации.
Для реплик клиента вместо качества работы RM показывается сила сигнала
вовлечённости или возражения. Анализ относится только к истории текущего запуска;
`/reset` очищает её.

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

Для работы нужен OpenAI-совместимый LLM API: локальный Ollama, OpenRouter, OpenAI или другой совместимый endpoint.

## Настройки

Все параметры читаются из `backend/.env` с префиксом `CHAT_`.

```env
CHAT_APP_NAME="EXANTE Scenario Trainer"
CHAT_LLM_MODEL=gemma4:12b
CHAT_LLM_BASE_URL=http://localhost:11434/v1
# Required by the OpenAI-compatible SDK and ignored by local Ollama.
CHAT_LLM_API_KEY=ollama
CHAT_LLM_TIMEOUT_SECONDS=60
CHAT_SQLITE_PATH=./backend/data/chat.sqlite3
CHAT_CHAT_STORAGE_MODE=sqlite_vec
```

`CHAT_CHAT_STORAGE_MODE=sqlite_vec` включает семантический поиск через `sqlite-vec`; значение `sqlite` оставляет обычную SQLite-историю без векторного поиска.

Для OpenRouter укажите `CHAT_LLM_BASE_URL=https://openrouter.ai/api/v1`, ключ в
`CHAT_LLM_API_KEY` и, при необходимости, JSON-объект `CHAT_LLM_EXTRA_HEADERS` с
`HTTP-Referer` и `X-Title`. Для OpenAI поменяйте URL на `https://api.openai.com/v1`
и задайте соответствующий ключ.

После обновления перенесите значения из старых `CHAT_OLLAMA_*`, `CHAT_OPENROUTER_*`
и `CHAT_OPENAI_*` в общие `CHAT_LLM_*`: старые имена больше не используются.

## Langfuse tracing

API автоматически создаёт один Langfuse trace на каждую реплику сценария. Traces
связаны `session_id` сценария, поэтому в Sessions view виден весь диалог; внутри
trace есть отдельный `retriever` для семантической памяти и LangChain generation с
моделью, задержкой и token usage (если их возвращает LLM endpoint).

Добавьте в `backend/.env` API keys проекта Langfuse. Не передавайте ключи в чат и
не добавляйте их в git:

```env
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=development
# Необязательно: релиз приложения для фильтрации и сравнений.
LANGFUSE_RELEASE=2026-08-31
```

Для US региона используйте `https://us.cloud.langfuse.com`; для self-hosted
инстанса — его URL. `LANGFUSE_TRACING_ENVIRONMENT` отделяет development/staging
traces от production. При отсутствии пары ключей tracing выключен без изменения
поведения API; его также можно временно выключить через
`LANGFUSE_TRACING_ENABLED=false`.

Перед отправкой данные traces проходят локальное маскирование email-адресов,
телефонных номеров, номеров карт и распространённых credential-пар. Это снижает
риск утечки PII, но для доменных идентификаторов и особых требований к compliance
добавьте правило в `backend/app/observability.py` или настройте masking в Langfuse.

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

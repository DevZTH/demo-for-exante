# Backend: FastAPI + LangChain Chat

Пример расширяемого backend для чата:

- API: FastAPI, автоматическая OpenAPI-схема на `/openapi.json`, Swagger UI на `/docs`.
- Chat engine: LangChain.
- Хранилище: SQLite для чатов/сообщений и `sqlite-vec` для семантической памяти.
- Настройки: `settings.py` + переменные окружения из `backend/.env`.
- LLM provider: `ollama`, локальный `demo`, `openrouter` или любой OpenAI-compatible endpoint.

## Структура

```text
backend/
  main.py                  # FastAPI app и lifespan
  settings.py              # Все настройки приложения
  requirements.txt         # Python-зависимости
  .env.example             # Пример конфигурации
  app/
    api.py                 # HTTP endpoints
    chat_engine.py         # LangChain chain и бизнес-логика
    domain.py              # Внутренние dataclass-модели
    embeddings.py          # Демо-эмбеддинги для sqlite-vec
    providers.py           # Фабрика LLM-провайдеров
    schemas.py             # Pydantic-схемы API
    storage.py             # SQLite/sqlite-vec репозиторий
```

## Быстрый запуск

```bash
cd /home/devz/exante_demo
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
bash backend/run.sh
```

После запуска:

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
- Healthcheck: `http://127.0.0.1:8000/api/v1/health`

## Настройки

Все ключевые настройки находятся в `backend/settings.py` и переопределяются через переменные окружения с префиксом `CHAT_`.

Основные параметры:

```env
CHAT_LLM_PROVIDER=ollama
CHAT_LLM_MODEL=gemma4:e2b
CHAT_OLLAMA_BASE_URL=http://localhost:11434
CHAT_SQLITE_PATH=./backend/data/chat.sqlite3
CHAT_CHAT_STORAGE_MODE=sqlite_vec
CHAT_HISTORY_WINDOW_MESSAGES=16
CHAT_SEMANTIC_MEMORY_LIMIT=6
CHAT_EMBEDDING_DIMENSIONS=64
```

`CHAT_CHAT_STORAGE_MODE`:

- `sqlite_vec`: сообщения пишутся в SQLite, а embeddings сообщений индексируются через `sqlite-vec`.
- `sqlite`: только обычная история сообщений в SQLite, без семантического поиска.

## Провайдеры LLM

### Ollama

```env
CHAT_LLM_PROVIDER=ollama
CHAT_LLM_MODEL=gemma4:e2b
CHAT_OLLAMA_BASE_URL=http://localhost:11434
```

Убедись, что модель скачана и Ollama запущена:

```bash
ollama pull gemma4:e2b
ollama serve
```

### Demo

Работает локально без API-ключей и без Ollama. Это только запасной режим для проверки UI, API и памяти LangChain:

```env
CHAT_LLM_PROVIDER=demo
CHAT_LLM_MODEL=local-memory-demo
```

### OpenRouter

```env
CHAT_LLM_PROVIDER=openrouter
CHAT_LLM_MODEL=openai/gpt-4o-mini
CHAT_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
CHAT_OPENROUTER_API_KEY=sk-or-v1-...
```

### OpenAI-compatible endpoint

Подходит для сервисов, которые реализуют OpenAI Chat Completions API.

```env
CHAT_LLM_PROVIDER=openai_compatible
CHAT_LLM_MODEL=local-model
CHAT_OPENAI_BASE_URL=http://localhost:11434/v1
CHAT_OPENAI_API_KEY=ollama
```

## API

Создать чат:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chats \
  -H "Content-Type: application/json" \
  -d '{"title":"Demo"}'
```

Отправить сообщение. Если `chat_id` не передан, backend создаст новый чат:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Привет! Запомни, что мой проект про EXANTE demo."}'
```

Продолжить существующий чат:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"chat_id":"<CHAT_ID>","message":"О чем мой проект?"}'
```

Получить историю:

```bash
curl http://127.0.0.1:8000/api/v1/chats/<CHAT_ID>/messages
```

## Как работает память

`storage.py` хранит сообщения в таблице `messages`. В режиме `sqlite_vec` каждое сообщение получает локальный deterministic embedding из `HashEmbeddings` и пишется в виртуальную таблицу `message_vectors`.

Перед запросом к модели `chat_engine.py` делает две вещи:

- берет последние `CHAT_HISTORY_WINDOW_MESSAGES` сообщений через `SQLiteChatMessageHistory`, совместимый с LangChain `BaseChatMessageHistory`, и передает их в `MessagesPlaceholder`;
- ищет похожие прошлые сообщения в `sqlite-vec` и добавляет их в системный контекст.

`HashEmbeddings` нужны только для демо, чтобы пример работал без отдельного embedding API. Для production лучше заменить их на реальные embeddings, например Ollama/OpenAI embeddings через LangChain.

## Точки расширения

- Добавить streaming endpoint: отдельный route в `api.py`, который вызывает streaming-методы LangChain.
- Добавить авторизацию: dependency в `api.py`, поле `user_id` в таблицы `chats` и `messages`.
- Добавить RAG по документам: отдельные таблицы/индексы sqlite-vec и отдельный retriever.
- Добавить новый LLM provider: новая ветка в `providers.py`, настройки в `settings.py`.
- Заменить embeddings: новая реализация `Embeddings` и подключение в `chat_engine.py`.

## Замечания

- `sqlite-vec` использует SQLite extension. Если окружение не разрешает загрузку extensions, поставь `CHAT_CHAT_STORAGE_MODE=sqlite`.
- В OpenAPI/Swagger не выводятся секреты, endpoint `/api/v1/settings` возвращает только безопасные runtime-настройки.

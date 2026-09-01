# EXANTE Scenario Trainer

Приложение тренирует Relationship Manager в сценарном диалоге с аватаром клиента EXANTE. В проект входят FastAPI API, React-интерфейс, консольный клиент и отдельный контур offline-evaluation.

## Что потребуется

- Python с поддержкой `venv`;
- Node.js и npm — только для React-интерфейса;
- доступный OpenAI-совместимый LLM endpoint: локальный Ollama, OpenRouter, OpenAI или другой совместимый сервис.

> При использовании Python 3.14 зависимости LangChain могут вывести предупреждение о совместимости Pydantic V1. Для рабочего окружения предпочтительны Python 3.11–3.13.

## Установка

Выполните команды из корня репозитория:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

cp backend/.env.example backend/.env
```

Установите зависимости web-интерфейса:

```bash
cd chat
npm install
cd ..
```

## Настройка LLM

Все настройки backend читаются из `backend/.env`. Шаблон уже содержит конфигурацию локального Ollama:



```env
CHAT_LLM_MODEL=gemma4:12b
CHAT_LLM_BASE_URL=http://localhost:11434/v1
CHAT_LLM_API_KEY=ollama
```

Перед запуском убедитесь, что Ollama запущен и модель установлена:

```bash
ollama pull gemma4:12b
```

Для OpenAI замените значения в `backend/.env`:

```env
CHAT_LLM_MODEL=gpt-4o-mini
CHAT_LLM_BASE_URL=https://api.openai.com/v1
CHAT_LLM_API_KEY=<ваш_ключ>
```

Для использования с OpenRouter:
```env
CHAT_LLM_MODEL=google/gemini-3.5-flash-lite
CHAT_LLM_BASE_URL=https://openrouter.ai/api/v1
CHAT_LLM_API_KEY=sk-or-v1-<>
```

Не добавляйте `backend/.env` и ключи API в git. Если режим `sqlite_vec` недоступен, установите в `.env` `CHAT_CHAT_STORAGE_MODE=sqlite`; тогда приложение продолжит работать без семантического поиска.

## Запуск API и web-интерфейса

Запустите backend в первом терминале:

```bash
source .venv/bin/activate
bash backend/run.sh
```

После запуска доступны:

- Swagger UI: <http://127.0.0.1:8000/docs>
- Проверка состояния: <http://127.0.0.1:8000/api/v1/health>

Во втором терминале запустите UI:

```bash
cd chat
npm run dev
```

Откройте адрес, который выведет Vite (обычно <http://127.0.0.1:5173>). По умолчанию UI обращается к `http://127.0.0.1:8000/api/v1`. Чтобы использовать другой API-адрес:

```bash
cd chat
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1 npm run dev
```

## Консольный клиент

Консольный клиент вызывает LangChain и LLM напрямую: он не поднимает FastAPI и хранит историю только до завершения процесса.

```bash
bash backend/run_cli.sh
```

Чтобы дополнительно видеть сигнал аватара после каждой реплики:

```bash
bash backend/run_cli.sh --show-signal
```

Фактический вывод справки (`bash backend/run_cli.sh --help`):

```text
usage: python -m backend.cli [-h] [--show-signal]

EXANTE scenario chat, directly through LangChain (no FastAPI).

options:
  -h, --help     show this help message and exit
  --show-signal  показывать state, trust, purchase_probability и done после
                 реплики
```

Команды внутри чата:

| Команда | Действие |
| --- | --- |
| `/analyze` | Запустить анализ всего текущего диалога супервайзером. |
| `/reset` | Очистить историю и начать новый диалог. |
| `/quit`, `/exit`, `/q` | Завершить консольный клиент. |

## Проверка разработки

Установите test-зависимости и запустите тесты:

```bash
source .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
pytest -q tests
```

Просмотреть доступные eval-наборы:

```bash
python -m evals.cli list-datasets
```

Подробности API, переменных окружения, хранения и Langfuse находятся в [backend/README.md](backend/README.md). Документация по архитектуре: [backend/architecture.md](backend/architecture.md) и [agent architech.md](<agent architech.md>).

# Ревизия deprecated-кода перед удалением обычного/demo-чата

Дата ревизии: 2026-08-30.

Цель следующего этапа: избавиться от demo-чата и обычных чатов без сценария, затем сузить архитектуру до сценарных диалогов EXANTE. На этом этапе код не удалялся и не рефакторился, собрана только информация.

## Текущий блокер запуска

- `backend/settings.py:31` содержит незакрытую строку `llm_model: str = "gemma4:12b`, из-за этого backend не импортируется. Проверка `python -m py_compile backend/settings.py` падает с `SyntaxError: unterminated string literal`.
- `backend/settings.py:34` задает `llm_timeout_seconds = -1`, но поле объявлено как `Field(..., gt=0)`. После исправления синтаксиса это станет валидационной ошибкой Pydantic.
- Эти правки уже есть в рабочем дереве до ревизии, поэтому здесь только зафиксированы.

## Карта текущей архитектуры

- `backend/main.py` инициализирует два параллельных сервиса: обычный `ChatEngine` и сценарный `AgentService`.
- Обычный чат идет через `POST /api/v1/chat` -> `ChatEngine.ask()`.
- Сценарий идет через `POST /api/v1/agent/chat` -> `AgentService.process_message()`.
- Оба режима пишут в одни таблицы `chats`, `messages`, `message_vectors`.
- В таблице `chats` нет признака сценария/типа диалога. Единственный явный маркер сценария сейчас находится в metadata assistant-сообщения: `{"mode": "agent"}`.
- Frontend хранит `scenarioChatIds` только в React state. После перезагрузки страницы сценарные чаты загружаются из `/chats`, но их тип не восстанавливается, поэтому продолжение может уйти в обычный `/chat`.
- Документация и названия проекта всё ещё описывают приложение как demo/OpenWebUI-like chat.

## Главные кандидаты на удаление

1. Обычный chat-flow:
   - `backend/app/chat_engine.py` целиком.
   - `POST /api/v1/chat` в `backend/app/api.py:70`.
   - `ChatRequest` и `ChatTurnResponse`, если они больше не используются отдельным обычным endpoint.
   - UI-кнопки/логика "Новый чат" и отправка в `/chat` в `chat/src/main.jsx`.

2. Demo LLM provider:
   - `DemoChatModel` в `backend/app/providers.py:70`.
   - Ветка `settings.llm_provider == "demo"` в `build_chat_model()`.
   - helper-функции demo-памяти в `backend/app/providers.py:136-206`.
   - Значение `"demo"` в `Settings.llm_provider`.
   - Ветка `demo -> local` в `_llm_endpoint()`.
   - Упоминания demo-провайдера в `backend/README.md` и `backend/.env.example`.

3. Generic chat API без сценария:
   - `POST /api/v1/chats` создает пустой обычный чат без сценария.
   - `GET /api/v1/chats`, `GET /api/v1/chats/{chat_id}`, `DELETE /api/v1/chats/{chat_id}`, `GET /api/v1/chats/{chat_id}/messages` пока нужны UI/истории, но должны стать scenario-aware или быть переименованы.

## Что нужно сохранить как основу

- `AgentService.process_message()` - текущий основной сценарный use case.
- `AgentResponse` / `AgentResponseData` / `AgentTurnResponse` - основа структурированного ответа сценария.
- `ChatRepository` и `SQLiteChatMessageHistory` - полезная инфраструктура хранения, но нуждаются в переименовании или добавлении признака `scenario`.
- `build_chat_model()` - оставить как фабрику реальных провайдеров, удалить только demo-ветку.
- `HashEmbeddings` технически помечен как demo, но сейчас используется и сценарием. Его нужно либо заменить на production embeddings, либо временно оставить как `LocalHashEmbeddings` без demo-позиционирования.

## Риски перед удалением

- Без миграции БД невозможно надежно отличить сценарные чаты от обычных.
- Простое удаление `/chat` сломает frontend, потому что `mode` по умолчанию сейчас `"chat"`, а `handleSubmit()` выбирает endpoint по `activeMode`.
- Удаление demo provider может сломать локальную разработку без Ollama/OpenRouter/OpenAI-compatible endpoint.
- `AgentService._get_agent_system_prompt()` дублирует/урезает сценарий из `backend/agent/customer.md`; есть риск, что реальное поведение агента отличается от документации.
- Поле `intetions` написано с опечаткой. Оно повторяется в prompt, backend schema и ответе. Исправление на `intentions` потребует совместимого перехода или явной миграции API.

## Функциональная ревизия backend

### `backend/main.py`

| Функция | Статус | Комментарий |
| --- | --- | --- |
| `lifespan()` | изменить | Инициализирует и `ChatEngine`, и `AgentService`. После удаления обычного чата нужно убрать `app.state.chat_engine` и импорт `ChatEngine`, оставить repository + scenario service. |

### `backend/settings.py`

| Функция/класс | Статус | Комментарий |
| --- | --- | --- |
| `Settings` | изменить | Убрать `"demo"` из `llm_provider`, обновить дефолты, исправить текущий синтаксис `llm_model`, привести `llm_timeout_seconds` к валидному значению. |
| `get_settings()` | оставить | Нужен как cached factory. После изменения Settings может остаться без изменений. |

### `backend/app/api.py`

| Функция | Статус | Комментарий |
| --- | --- | --- |
| `get_settings()` | оставить | Dependency для runtime settings. |
| `get_repository()` | оставить/переименовать позже | Нужен scenario API. Название можно оставить, пока repository общий. |
| `get_chat_engine()` | удалить | Обслуживает только обычный `/chat`. |
| `get_agent_service()` | оставить | Основная dependency сценария. |
| `health()` | оставить | Нужен для диагностики. |
| `read_settings()` | изменить | Сейчас возвращает demo/provider info и chat terminology. После удаления demo убрать demo mapping и проверить поля. |
| `_llm_endpoint()` | изменить | Удалить ветку `demo -> local`; возможно перенести в Settings/Provider info. |
| `chat()` | удалить | Это обычный чат без сценария (`POST /chat`). |
| `create_chat()` | удалить или заменить | Позволяет создавать пустой обычный чат через `POST /chats`. Для сценариев лучше создавать через `/agent/chat` или новый `/scenarios`. |
| `list_chats()` | изменить | Сейчас возвращает все чаты без фильтра типа. Нужно фильтровать/переименовать в scenario list. |
| `get_chat()` | изменить | Нужно проверять, что запрошенный chat является сценарием. |
| `delete_chat()` | изменить | Можно оставить удаление сценария, но лучше переименовать endpoint/метод. |
| `list_messages()` | изменить | Нужно отдавать только сообщения сценарных диалогов и корректно мапить assistant JSON. |
| `agent_chat()` | оставить/переименовать | Основной сценарный endpoint. Возможное будущее имя: `/scenarios/{id}/turns` или `/scenario/chat`. |

### `backend/app/chat_engine.py`

| Функция/класс | Статус | Комментарий |
| --- | --- | --- |
| `ChatEngine` | удалить | Целиком обслуживает обычный чат без сценария. |
| `ChatEngine.__init__()` | удалить | Создает generic chain и локальные hash embeddings для обычного чата. |
| `ChatEngine.ask()` | удалить | Главный обычный chat use case. |
| `ChatEngine._build_chain()` | удалить | Prompt обычного assistant. |
| `ChatEngine._semantic_context()` | удалить/объединить | Дублирует логику `AgentService._semantic_context()`. Если нужна общая память, вынести в shared helper перед удалением класса. |
| `ChatEngine._format_semantic_context()` | удалить/объединить | Дублирует formatter из agent service, отличается только текстом fallback. |
| `ChatEngine._content_from_response()` | удалить/объединить | Дублирует agent service helper. |
| `ChatEngine._saved_turn()` | удалить/объединить | Дублирует agent service helper. |
| `ChatEngine._title_from()` | удалить/заменить | Для сценариев есть отдельный title helper. |

### `backend/app/agent_service.py`

| Функция/класс | Статус | Комментарий |
| --- | --- | --- |
| `AgentResponse` | оставить/типизировать | Лучше заменить на Pydantic/dataclass и синхронизировать с `AgentResponseData`. |
| `AgentResponse.__init__()` | изменить | Нет type validation/range validation; опечатка `intetions`. |
| `AgentResponse.to_dict()` | оставить/изменить | Нужен для сохранения JSON. При миграции поля `intetions` учесть совместимость. |
| `AgentResponse.to_json()` | оставить | Нужен для записи assistant message. |
| `AgentResponse.from_json()` | изменить | Сейчас `bool(data.get("done", False))` сделает `True` из строки `"false"`. Нет проверки допустимых `state`, trust/probability clamp. |
| `AgentService` | оставить | Основной сервис сценария. |
| `AgentService.__init__()` | изменить | Использует `HashEmbeddings`; после удаления demo лучше инжектить embeddings/provider явно. |
| `AgentService.process_message()` | оставить/изменить | Основной сценарный turn. Нужно сохранять тип сценария на уровне chat, не только metadata сообщения. |
| `AgentService._build_chain()` | оставить/обобщить | Дублирует структуру `ChatEngine._build_chain()`. После удаления ChatEngine может остаться здесь. |
| `AgentService._get_agent_system_prompt()` | изменить | Сейчас возвращает embedded prompt и не читает `backend/agent/customer.md`, хотя docstring говорит обратное. |
| `AgentService._semantic_context()` | оставить/обобщить | Нужна сценарной памяти. |
| `AgentService._format_semantic_context()` | оставить | Нужна prompt context. Возможно скрывать JSON assistant-сообщений или форматировать только `reply`. |
| `AgentService._content_from_response()` | оставить/обобщить | Нужна для LangChain responses. |
| `AgentService._saved_turn()` | оставить/обобщить | Нужна для возврата сохраненного turn. |
| `AgentService._title_from()` | изменить | Название "New agent chat" лучше заменить на сценарную терминологию. |

### `backend/app/providers.py`

| Функция/класс | Статус | Комментарий |
| --- | --- | --- |
| `build_chat_model()` | изменить | Удалить demo branch, оставить `ollama`, `openrouter`, `openai_compatible`. Проверить timeout units для OpenRouter. |
| `_secret_value()` | оставить | Нужен для SecretStr/env fallback. |
| `DemoChatModel` | удалить | Локальный demo-бот, прямой кандидат на deprecated. |
| `DemoChatModel._llm_type` | удалить | Часть demo provider. |
| `DemoChatModel._call()` | удалить | Часть demo provider и обычной demo-памяти. |
| `_extract_facts()` | удалить | Используется только `DemoChatModel._call()`. |
| `_clean_fact()` | удалить | Используется только demo fact extraction. |
| `_is_memory_question()` | удалить | Используется только demo model. |
| `_asks_name()` | удалить | Используется только demo model. |
| `_asks_project()` | удалить | Используется только demo model. |
| `_latest_name()` | удалить | Используется только demo model. |
| `_latest_project_fact()` | удалить | Используется только demo model. |

### `backend/app/embeddings.py`

| Функция/класс | Статус | Комментарий |
| --- | --- | --- |
| `HashEmbeddings` | изменить или заменить | Документирован как demo semantic memory, но используется и `ChatEngine`, и `AgentService`. |
| `HashEmbeddings.__init__()` | оставить при временном использовании | Только хранит dimensions. |
| `HashEmbeddings.embed_documents()` | оставить/заменить | LangChain embeddings API. |
| `HashEmbeddings.embed_query()` | оставить/заменить | Используется для semantic memory. |
| `HashEmbeddings._embed()` | оставить/заменить | Детерминированный hash embedding; production-качество низкое. |

### `backend/app/memory.py`

| Функция/класс | Статус | Комментарий |
| --- | --- | --- |
| `SQLiteChatMessageHistory` | оставить/переименовать | Нужна сценарная история. Название можно позже заменить на `SQLiteScenarioMessageHistory`. |
| `SQLiteChatMessageHistory.__init__()` | изменить | Добавить/передавать metadata сценария, если storage будет scenario-aware. |
| `SQLiteChatMessageHistory.messages` | оставить | Нужна LangChain history. Для agent-сообщений надо решить, отдавать полный JSON или только `reply`. |
| `SQLiteChatMessageHistory.add_messages()` | оставить/изменить | Нужна запись turn. Возможно индексировать только видимый текст, а не весь JSON. |
| `SQLiteChatMessageHistory.clear()` | оставить | Может пригодиться для перезапуска сценария. |
| `SQLiteChatMessageHistory._metadata_for()` | изменить | Сейчас добавляет только `memory=langchain` и metadata role; для сценариев нужен устойчивый marker. |
| `to_langchain_message()` | оставить/изменить | Для assistant JSON может быть нужен conversion в видимую реплику. |
| `role_from_langchain_message()` | оставить | Общая adapter-функция. |
| `content_from_langchain_message()` | оставить | Общая adapter-функция. |

### `backend/app/storage.py`

| Функция/класс | Статус | Комментарий |
| --- | --- | --- |
| `ChatRepository` | оставить/переименовать | Core persistence. Для цели нужен `chat_type/scenario_id` на уровне `chats`. |
| `ChatRepository.__init__()` | оставить/изменить | После миграции принять настройки scenario storage. |
| `ChatRepository.vector_enabled` | оставить | Управляет sqlite-vec. |
| `ChatRepository.init_db()` | изменить | Добавить поле типа диалога/сценария и индексы; продумать миграцию существующих данных. |
| `ChatRepository.create_chat()` | изменить | Должен создавать сценарный chat с обязательным типом, а не произвольный обычный chat. |
| `ChatRepository.ensure_chat()` | изменить | Сейчас создает chat с произвольным id, если не найден. Для сценария это может скрывать ошибку неверного id. |
| `ChatRepository.get_chat()` | изменить | Нужно уметь проверять тип сценария. |
| `ChatRepository.list_chats()` | изменить | Нужен фильтр по типу/сценарию; сейчас смешивает все. |
| `ChatRepository.delete_chat()` | оставить/изменить | Нужен, но как delete scenario conversation. |
| `ChatRepository.clear_messages()` | оставить | Полезно для restart/reset сценария. |
| `ChatRepository.add_message()` | изменить | Добавить scenario metadata/видимое содержимое для индексации. |
| `ChatRepository.get_message()` | оставить | Нужен после insert. |
| `ChatRepository.list_messages()` | изменить | Нужен фильтр/проверка scenario ownership. |
| `ChatRepository.search_similar_messages()` | изменить | Сейчас ищет по JSON assistant content; для agent лучше индексировать/искать видимые `reply` или отдельное поле. |
| `ChatRepository.health()` | оставить | Диагностика storage. |
| `ChatRepository._connect()` | оставить | Общий sqlite connection helper. |
| `ChatRepository._load_sqlite_vec()` | оставить | Нужен только если остается sqlite-vec. |
| `ChatRepository._now()` | оставить | Общий timestamp helper. |
| `ChatRepository._parse_dt()` | оставить | Общий mapper helper. |
| `ChatRepository._serialize_vector()` | оставить | Нужен sqlite-vec. |
| `ChatRepository._chat_from_row()` | изменить | После добавления типа чата расширить `ChatRecord`. |
| `ChatRepository._message_from_row()` | изменить | Возможно добавить parsed/visible payload или scenario metadata. |

### `backend/app/schemas.py`

| Класс/метод | Статус | Комментарий |
| --- | --- | --- |
| `ChatCreateRequest` | удалить/заменить | Нужен только generic `POST /chats`. |
| `ChatResponse` | изменить/переименовать | Пока нужен для scenario response, но должен отражать тип/сценарий. |
| `ChatResponse.from_record()` | изменить | После расширения `ChatRecord` добавить поля сценария. |
| `MessageResponse` | оставить/изменить | Нужен истории. Возможно добавить `visible_text` или не отдавать raw JSON в UI. |
| `MessageResponse.from_record()` | изменить | Может мапить assistant JSON безопаснее. |
| `SemanticMatchResponse` | оставить | Нужен, если сохраняем semantic context. |
| `SemanticMatchResponse.from_match()` | оставить/изменить | Зависит от `MessageResponse`. |
| `ChatRequest` | удалить/заменить | Обычный `/chat` request. |
| `ChatTurnResponse` | удалить/заменить | Обычный `/chat` response. |
| `ChatTurnResponse.from_turn()` | удалить/заменить | Используется только обычным chat endpoint. |
| `SettingsResponse` | изменить | Убрать demo/provider fields, если UI больше не показывает модель как chat selector. |
| `AgentResponseData` | оставить/изменить | Основная response schema. Исправить/мигрировать `intetions`. |
| `AgentRequest` | оставить/переименовать | Основной request сценария. Возможное имя: `ScenarioTurnRequest`. |
| `AgentTurnResponse` | оставить/переименовать | Основной response сценария. |
| `AgentTurnResponse.from_turn_and_agent()` | оставить/изменить | Убрать `Any`, использовать общий тип/модель `AgentResponse`. |

### `backend/app/domain.py`

| Класс | Статус | Комментарий |
| --- | --- | --- |
| `ChatRecord` | изменить/переименовать | Добавить `mode/type/scenario_id` или заменить на `ScenarioRecord`. |
| `MessageRecord` | оставить/изменить | Нужен истории. Возможно добавить parsed payload/visible content. |
| `SemanticMatch` | оставить | Нужен semantic memory. |
| `ChatTurn` | изменить/переименовать | Сейчас общий тип для ordinary и agent flows. После удаления ordinary flow лучше сделать `ScenarioTurn`. |

## Функциональная ревизия frontend

### `chat/src/main.jsx`

| Функция/константа | Статус | Комментарий |
| --- | --- | --- |
| `API_BASE_URL` | оставить | Нужен для API calls. |
| `suggestions` | удалить/заменить | Текущие подсказки про generic memory demo, не про EXANTE scenario. |
| `DEFAULT_SCENARIO_MESSAGE` | оставить/проверить UX | Автостарт сценария через первое сообщение. Возможно лучше начинать пустой сценарий серверным endpoint. |
| `welcomeMessage` | удалить/заменить | Текст generic chat/demo memory. |
| `formatTime()` | оставить | UI helper. |
| `nowTime()` | оставить | UI helper. |
| `formatChatMeta()` | оставить | UI helper для списка. |
| `extractVisibleAssistantText()` | оставить/изменить | Сейчас скрывает JSON, но fallback позволяет показывать raw non-JSON. После удаления ordinary chat можно строже работать с `agent_response.reply`. |
| `mapMessage()` | изменить | Сейчас мапит generic message API. Для сценариев лучше использовать `agent_response.reply` или server-side visible field. |
| `apiFetch()` | оставить | Общий HTTP helper. |
| `App()` | изменить | Главный UI сейчас смешивает ordinary chat и scenario mode. Нужно сделать scenario-only state machine. |
| `loadInitialState()` | изменить | Загружает `/chats` и выбирает первый чат без понимания типа. Нужно грузить только scenarios. |
| `refreshChats()` | изменить | Сейчас дергает `/chats`; должен дергать scenario-aware endpoint. |
| `selectChat()` | изменить | Сейчас определяет mode через transient `scenarioChatIds`; после reload ломается. Нужен тип из backend. |
| `handleSubmit()` | изменить | Сейчас выбирает endpoint между `/chat` и `/agent/chat`. После удаления ordinary chat всегда должен отправлять scenario turn. |
| `handleTextareaKeyDown()` | оставить | UI helper. |
| `startNewChat()` | удалить | Прямой UI вход в обычный чат без сценария. |
| `startNewScenario()` | оставить/изменить | Основной старт сценария. Нужно решить, должен ли frontend сам отправлять default message. |
| JSX кнопка brand "Open Chat" | изменить | Сейчас вызывает `startNewChat()` и ведет в обычный чат. |
| JSX кнопка "Новый чат" | удалить | Обычный chat entrypoint. |
| JSX кнопка "Новый сценарий" | оставить | Основной entrypoint. |
| JSX model selector | изменить | Сейчас показывает модель или `EXANTE scenario`; вероятно заменить на статус сценария/персону. |
| JSX suggestions | удалить/заменить | Generic demo prompts. |

### `chat/src/styles.css`

| Область | Статус | Комментарий |
| --- | --- | --- |
| `.new-chat-button` | удалить | Связан с ordinary chat UI. |
| `.new-scenario-button` | оставить/переименовать | Основная кнопка сценария. |
| `.model-select.scenario-mode` | изменить | Может стать scenario status control. |
| `.chat-list`, `.chat-item`, `.chat-panel` | переименовать позже | Работают как UI, но терминология chat останется в CSS. |
| `.suggestions` | удалить/заменить | Сейчас обслуживает generic demo prompts. |

## Документация и конфиги

- `backend/README.md` описывает проект как demo chat, содержит demo provider и обычные `/chat` примеры. Требует переписывания под scenario-only API.
- `backend/.env.example` содержит закомментированный demo provider. Удалить после удаления `DemoChatModel`.
- `chat/README.md` и `chat/index.html` называют UI `OpenWebUI-like React Chat`. Переименовать под EXANTE scenario trainer.
- `AGENT_IMPLEMENTATION.md` явно фиксирует, что обычный `/api/v1/chat` сохранен. После удаления обычного чата документ станет устаревшим.
- `backend/agent/AGENT_SYSTEM.md` и `scenario.md` в целом полезны, но нужно синхронизировать с реальным prompt в `AgentService._get_agent_system_prompt()`.

## Рекомендуемый порядок следующего рефакторинга

1. Сначала починить `backend/settings.py`, чтобы backend снова импортировался.
2. Добавить в storage устойчивый признак типа диалога: например `chats.kind = 'scenario'`.
3. Мигрировать/пометить существующие сценарные чаты. Минимальный эвристический признак: наличие assistant-сообщений с metadata `mode=agent`.
4. Сделать backend endpoints scenario-aware: list/get/messages должны возвращать только сценарии или иметь новые `/scenarios` пути.
5. Перевести frontend в scenario-only режим: убрать `mode='chat'`, `scenarioChatIds`, `startNewChat()` и ветку отправки в `/chat`.
6. Удалить `ChatEngine`, `ChatRequest`, `ChatTurnResponse` и `/chat`.
7. Удалить demo provider и связанные helper-функции из `providers.py`.
8. Обновить документацию и `.env.example`.
9. После каждого шага запускать backend import/API smoke и frontend build.

## Проверки, выполненные во время ревизии

- `rg --files` для карты проекта.
- `rg -n` по `demo`, `chat`, `scenario`, `/chat`, `/chats`, `ChatEngine`, `DemoChatModel`, `scenarioChatIds`.
- `git diff -- backend/settings.py chat/src/main.jsx chat/src/styles.css` для понимания уже существующих незакоммиченных изменений.
- `python -m py_compile backend/settings.py` - упал на `backend/settings.py:31`, как описано выше.

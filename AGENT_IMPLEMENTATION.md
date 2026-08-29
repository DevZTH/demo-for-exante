w# Добавлены компоненты диалога агента

## ✅ Выполнено

### 1. Создан сервис агента (`backend/app/agent_service.py`)
- **AgentService** - управляет взаимодействием с персоной клиента
- **AgentResponse** - структурированный ответ агента с полями:
  - `reply` - реплика клиента (видна продавцу)
  - `intetions` - внутреннее состояние (скрыто)
  - `state` - стадия engagement (curious/considering/interested/evaluating/ready_for_next_step/ready_to_fund/rejected)
  - `trust` - доверие к RM (0-100)
  - `purchase_probability` - вероятность открыть счёт (0-100)
  - `done` - завершена ли беседа

### 2. Расширены схемы (`backend/app/schemas.py`)
- `AgentResponseData` - Pydantic model для ответа агента
- `AgentRequest` - запрос к агенту
- `AgentTurnResponse` - полный ответ турна беседы

### 3. Добавлены API endpoints (`backend/app/api.py`)
- `POST /api/v1/agent/chat` - главный endpoint для диалога
- Dependency injection для `AgentService`

### 4. Обновлена инициализация (`backend/main.py`)
- `AgentService` инициализируется при запуске приложения
- Интегрирована с существующим `ChatRepository`

### 5. Документация (`backend/agent/AGENT_SYSTEM.md`)
- Полное описание системы агента
- Примеры использования API
- Описание персоны и сценария

## 🔒 Сохранено существующее

✓ Обычный chat endpoint (`/api/v1/chat`) работает как раньше  
✓ Все хранилища и история работают без изменений  
✓ Настройки LLM провайдеров не затронуты  
✓ Фронтенд не требует изменений  

## 🚀 Использование

```bash
# Тест в curl
curl -X POST "http://localhost:8000/api/v1/agent/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Здравствуйте, я интересуюсь вашими услугами",
    "chat_id": "session_123"
  }'
```

## 📋 Перед запуском

Убедитесь что установлены зависимости:

```bash
pip install -r requirements.txt
```

## ⚙️ Конфигурация

Агент использует системный промпт на русском языке, основанный на `customer.md`.

Промпт содержит:
- Полный профиль персоны
- Правила изменения trust и purchase_probability
- Типичные возражения и ответы на них
- Разрешённые состояния

## 🔗 Интеграция фронтенда

В `chat/src/` можно добавить компонент для агент-чата:

```javascript
// Вариант компонента для фронтенда
async function sendToAgent(message, chatId) {
  const res = await fetch(`${API_URL}/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, chat_id: chatId })
  });
  
  const data = await res.json();
  
  // data.agent_response содержит:
  // - reply (что говорит клиент)
  // - state (какая стадия)
  // - trust (доверие)
  // - purchase_probability (вероятность покупки)
  // - done (завершена ли беседа)
  
  return data;
}
```

## 📝 Расширение в будущем

Система спроектирована untuk расширения:

1. **Новые сценарии** - создать класс-наследник `AgentService` с другим промптом
2. **Другие персоны** - изменить метод `_get_agent_system_prompt()`
3. **Метрики** - добавить поля в `AgentResponse`
4. **Аналитика** - использовать `metadata` для сбора данных

---

**Статус**: ✅ Готово к тестированию и запуску

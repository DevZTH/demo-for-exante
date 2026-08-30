# EXANTE Scenario Trainer

React-интерфейс для тренировки диалога Relationship Manager с клиентом EXANTE. Интерфейс работает только со сценарным API: список сценариев, их история и новые turns.

## Запуск

```bash
npm install
npm run dev
```

Перед запуском поднимите backend из корня проекта:

```bash
bash backend/run.sh
```

По умолчанию UI использует `http://127.0.0.1:8000/api/v1`. Другой адрес можно задать так:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1 npm run dev
```

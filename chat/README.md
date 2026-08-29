# OpenWebUI-like React Chat

Небольшой демо-чат на React с оформлением, близким к OpenWebUI: боковая история диалогов, верхний селектор модели, поток сообщений и нижнее поле ввода.

## Запуск

```bash
npm install
npm run dev
```

Перед запуском UI подними backend из корня проекта:

```bash
bash backend/run.sh
```

По умолчанию UI ходит в `http://127.0.0.1:8000/api/v1`. Для другого backend URL можно задать:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1 npm run dev
```

После запуска Vite покажет локальный URL.

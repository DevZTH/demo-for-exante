env CHAT_LLM_PROVIDER=ollama CHAT_LLM_MODEL=gemma4:e2b CHAT_SQLITE_PATH=/home/devz/exante_demo/backend/data/chat.sqlite3 
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000

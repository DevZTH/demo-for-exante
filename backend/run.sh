#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export CHAT_LLM_PROVIDER="${CHAT_LLM_PROVIDER:-ollama}"
export CHAT_LLM_MODEL="${CHAT_LLM_MODEL:-gemma4:e2b}"
export CHAT_SQLITE_PATH="${CHAT_SQLITE_PATH:-$ROOT_DIR/backend/data/chat.sqlite3}"

".venv/bin/uvicorn" backend.main:app --host 127.0.0.1 --port 8000

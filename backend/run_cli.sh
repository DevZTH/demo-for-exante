#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "Виртуальное окружение .venv не найдено." >&2
  echo "Создайте его и установите зависимости:" >&2
  echo "  python -m venv .venv" >&2
  echo "  .venv/bin/python -m pip install -r backend/requirements.txt" >&2
  exit 1
fi

cd "$ROOT_DIR"
exec "$PYTHON" -m backend.cli "$@"

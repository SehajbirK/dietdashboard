#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"

if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

pip install -r requirements.txt

export BACKEND_URL="${BACKEND_URL:-http://localhost:7071}"

echo "Starting frontend on http://127.0.0.1:5000 (BACKEND_URL=$BACKEND_URL)"
"$PY" app.py


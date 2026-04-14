#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
PORT_BASE="${FUNC_PORT:-7071}"

if ! command -v func >/dev/null 2>&1; then
  echo "Azure Functions Core Tools (func) not found."
  exit 1
fi

if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

pip install -r requirements.txt

"$PY" scripts/create_local_settings.py

echo "Installing dependencies into .python_packages as a fallback..."
bash scripts/install_func_deps.sh

echo "Starting Azure Functions host..."

pick_port() {
  local start="$1"
  local end="$2"
  local p
  for p in $(seq "$start" "$end"); do
    if command -v lsof >/dev/null 2>&1; then
      if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
        continue
      fi
    fi
    echo "$p"
    return 0
  done
  return 1
}

PORT="$(pick_port "$PORT_BASE" 7080 || true)"
if [ -z "${PORT:-}" ]; then
  echo "No free port found in range ${PORT_BASE}-7080."
  exit 1
fi

echo "Backend URL: http://localhost:${PORT}"
echo "Health check: http://localhost:${PORT}/api/health"

func start --port "$PORT"

#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"

echo "Installing backend deps into .python_packages (for Azure Functions Core Tools)..."
mkdir -p .python_packages/lib/site-packages

"$PY" -m pip install -r requirements.txt --target ".python_packages/lib/site-packages"

echo "Done."


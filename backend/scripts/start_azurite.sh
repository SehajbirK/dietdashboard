#!/usr/bin/env bash
set -euo pipefail

AZURITE_DIR="${AZURITE_DIR:-/tmp/azurite}"
mkdir -p "$AZURITE_DIR"

echo "Starting Azurite in: $AZURITE_DIR"
echo "Blob:  http://127.0.0.1:10000"
echo "Queue: http://127.0.0.1:10001"
echo "Table: http://127.0.0.1:10002"

npx -y azurite@latest \
  --silent \
  --location "$AZURITE_DIR" \
  --debug "$AZURITE_DIR/debug.log" \
  --blobHost 127.0.0.1 --blobPort 10000 \
  --queueHost 127.0.0.1 --queuePort 10001 \
  --tableHost 127.0.0.1 --tablePort 10002


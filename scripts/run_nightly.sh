#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
export PATH="$HOME/.local/bin:/usr/local/bin:/snap/bin:$PATH"

docker compose up -d searxng || echo "searxng not started, search discovery will be skipped" >&2
scripts/llama_server.sh start

status=0
uv run scholaradar run "$@" || status=$?

scripts/llama_server.sh stop
exit "$status"

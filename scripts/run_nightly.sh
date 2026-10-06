#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
export PATH="$HOME/.local/bin:$PATH"

docker compose up -d searxng
docker compose --profile llm up -d llama

for _ in $(seq 1 120); do
  if curl -fs http://localhost:8080/health >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

status=0
uv run scholarship-radar run "$@" || status=$?

docker compose --profile llm stop llama
exit "$status"

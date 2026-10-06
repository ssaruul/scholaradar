#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

MODELS=(
  "Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf|32768|4"
  "gemma-3-27b-it-Q4_K_M.gguf|32768|4"
  "Qwen3-32B-Q4_K_M.gguf|16384|2"
)

for entry in "${MODELS[@]}"; do
  IFS='|' read -r file ctx parallel <<<"$entry"
  echo "=== $file (ctx $ctx, parallel $parallel)"
  docker compose --profile llm stop llama >/dev/null 2>&1 || true
  LLAMA_MODEL="$file" LLAMA_CTX="$ctx" LLAMA_PARALLEL="$parallel" docker compose --profile llm up -d llama
  for _ in $(seq 1 120); do
    curl -fs http://localhost:8080/health >/dev/null 2>&1 && break
    sleep 5
  done
  uv run scholarship-radar benchmark --model "${file%.gguf}" "$@"
done
docker compose --profile llm stop llama

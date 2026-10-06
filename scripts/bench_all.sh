#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/usr/local/bin:/snap/bin:$PATH"

MODELS=(
  "gemma-4-12b-it-Q4_K_M.gguf|65536|4"
  "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf|65536|4"
  "Qwen3.5-27B-Q4_K_M.gguf|65536|4"
  "gemma-4-31B-it-Q4_K_M.gguf|32768|2"
)

for entry in "${MODELS[@]}"; do
  IFS='|' read -r file ctx parallel <<<"$entry"
  echo "=== $file (ctx $ctx, parallel $parallel)"
  scripts/llama_server.sh stop >/dev/null 2>&1 || true
  LLAMA_MODEL="$file" LLAMA_CTX="$ctx" LLAMA_PARALLEL="$parallel" scripts/llama_server.sh start
  uv run scholarship-radar benchmark --model "${file%.gguf}" "$@"
done
scripts/llama_server.sh stop

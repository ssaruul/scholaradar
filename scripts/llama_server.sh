#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/usr/local/bin:/snap/bin:$PATH"
if [ -f .env ]; then
  while IFS='=' read -r key value; do
    case "$key" in ''|\#*) continue ;; esac
    if [ -z "${!key:-}" ]; then
      export "$key=$value"
    fi
  done < .env
fi

MODE="${LLAMA_MODE:-docker}"
PORT="${LLAMA_PORT:-8089}"

resolve_models_dir() {
  local pattern="${MODELS_DIR:-$HOME/models/gguf}"
  local match
  for match in $pattern; do
    if [ -d "$match" ]; then
      echo "$match"
      return 0
    fi
  done
  echo "no directory matches MODELS_DIR=$pattern (is the drive mounted?)" >&2
  return 1
}

MODELS_PATH="$(resolve_models_dir)"
MODEL_FILE="$MODELS_PATH/${LLAMA_MODEL:?LLAMA_MODEL not set}"
PID_FILE="data/llama-server.pid"
mkdir -p data/logs

wait_healthy() {
  for _ in $(seq 1 120); do
    if curl -fs "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  echo "llama-server did not become healthy on port ${PORT}" >&2
  return 1
}

start() {
  if [ "$MODE" = "native" ]; then
    BIN="${LLAMA_BIN:?LLAMA_BIN must point at the llama.cpp directory containing llama-server}"
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "llama-server already running (pid $(cat "$PID_FILE"))"
    else
      echo "starting llama-server with $MODEL_FILE"
      nohup "$BIN/llama-server" -m "$MODEL_FILE" --alias local \
        -c "${LLAMA_CTX:-65536}" --parallel "${LLAMA_PARALLEL:-4}" -ngl 99 \
        --flash-attn on -ctk "${LLAMA_KV_TYPE:-q8_0}" -ctv "${LLAMA_KV_TYPE:-q8_0}" \
        --jinja --host 127.0.0.1 --port "$PORT" \
        >> "data/logs/llama-server.log" 2>&1 &
      echo $! > "$PID_FILE"
    fi
  else
    MODELS_DIR="$MODELS_PATH" docker compose --profile llm up -d llama
  fi
  wait_healthy
}

stop() {
  if [ "$MODE" = "native" ]; then
    if [ -f "$PID_FILE" ]; then
      kill "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
    fi
  else
    docker compose --profile llm stop llama
  fi
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  *) echo "usage: $0 start|stop" >&2; exit 2 ;;
esac

#!/usr/bin/env bash
set -euo pipefail

REPO="${SCHOLARADAR_REPO:-https://github.com/ssaruul/scholaradar}"
DIR="${SCHOLARADAR_DIR:-$HOME/scholaradar}"
BACKEND="${SCHOLARADAR_BACKEND:-vulkan}"
MODEL_REPO="unsloth/gemma-4-26B-A4B-it-GGUF"
MODEL_FILE="gemma-4-26B-A4B-it-UD-Q4_K_M.gguf"
WITH_MODEL=1
WITH_CRON=1
WITH_LLM=1

for arg in "$@"; do
  case "$arg" in
    --no-model) WITH_MODEL=0 ;;
    --no-cron) WITH_CRON=0 ;;
    --no-llm) WITH_LLM=0 ;;
    --backend=*) BACKEND="${arg#*=}" ;;
    --dir=*) DIR="${arg#*=}" ;;
    --small) MODEL_REPO="unsloth/gemma-4-12b-it-GGUF"; MODEL_FILE="gemma-4-12b-it-Q4_K_M.gguf" ;;
    -h|--help)
      echo "usage: install.sh [--dir=PATH] [--backend=vulkan|cuda-12.8|cuda-13.4|rocm|cpu] [--small] [--no-model] [--no-llm] [--no-cron]"
      exit 0 ;;
    *) echo "unknown option $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n==> %s\n' "$*"; }

if ! command -v uv >/dev/null 2>&1; then
  say "installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }

if [ -d "$DIR/.git" ]; then
  say "updating $DIR"
  git -C "$DIR" pull --ff-only
else
  say "cloning into $DIR"
  git clone "$REPO" "$DIR"
fi
cd "$DIR"

say "installing Python dependencies"
uv sync

[ -f .env ] || cp .env.example .env
MODELS_DIR="$HOME/models/gguf"
mkdir -p "$MODELS_DIR"
sed -i.bak "s|^MODELS_DIR=.*|MODELS_DIR=$MODELS_DIR|; s|^LLAMA_MODEL=.*|LLAMA_MODEL=$MODEL_FILE|" .env && rm -f .env.bak

if [ "$WITH_LLM" = 1 ]; then
  say "installing llama.cpp ($BACKEND)"
  output=$(uv run scholaradar llm install --backend "$BACKEND")
  echo "$output"
  bin_dir=$(printf '%s\n' "$output" | sed -n 's/^LLAMA_BIN=//p' | tail -1)
  if [ -n "$bin_dir" ]; then
    sed -i.bak "s|^LLAMA_MODE=.*|LLAMA_MODE=native|; s|^LLAMA_BIN=.*|LLAMA_BIN=$bin_dir|" .env && rm -f .env.bak
    grep -q '^LLAMA_MODE=' .env || printf 'LLAMA_MODE=native\nLLAMA_BIN=%s\n' "$bin_dir" >> .env
  fi
fi

if [ "$WITH_MODEL" = 1 ] && [ ! -f "$MODELS_DIR/$MODEL_FILE" ]; then
  say "downloading $MODEL_FILE (this is the slow part)"
  uvx --from huggingface_hub hf download "$MODEL_REPO" "$MODEL_FILE" --local-dir "$MODELS_DIR"
fi

say "starting the search engine"
if command -v docker >/dev/null 2>&1; then
  docker compose up -d searxng || echo "could not start SearXNG; search discovery will be skipped until Docker works"
else
  echo "Docker not found; install it to enable web search discovery (anchor sources still work)"
fi

say "creating the database"
uv run scholaradar init-db

if [ "$WITH_CRON" = 1 ] && command -v crontab >/dev/null 2>&1; then
  line="0 3 * * * $DIR/scripts/run_nightly.sh >> $DIR/data/logs/nightly.log 2>&1"
  if ! crontab -l 2>/dev/null | grep -Fq "$DIR/scripts/run_nightly.sh"; then
    say "scheduling the nightly run at 03:00"
    (crontab -l 2>/dev/null; echo "$line") | crontab -
  fi
fi

say "done"
echo "First run (takes a while, then opens the dashboard):"
echo "  cd $DIR && uv run scholaradar nightly --open"

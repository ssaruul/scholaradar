#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/usr/local/bin:/snap/bin:$PATH"
mkdir -p data/logs
exec uv run scholaradar nightly "$@"

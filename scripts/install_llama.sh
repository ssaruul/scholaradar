#!/usr/bin/env bash
set -euo pipefail

BACKEND="${1:-vulkan}"
DEST="${2:-$HOME/.local/opt}"
API="https://api.github.com/repos/ggml-org/llama.cpp/releases"

tag=$(curl -fsSL "$API?per_page=5" | grep -oE '"tag_name": *"b[0-9]+"' | head -1 | grep -oE 'b[0-9]+')
case "$BACKEND" in
  vulkan) asset="llama-${tag}-bin-ubuntu-vulkan-x64.tar.gz" ;;
  cuda-12.8) asset="llama-${tag}-bin-ubuntu-cuda-12.8-x64.tar.gz" ;;
  cuda-13.4) asset="llama-${tag}-bin-ubuntu-cuda-13.4-x64.tar.gz" ;;
  rocm) asset="llama-${tag}-bin-ubuntu-rocm-10.0-x64.tar.gz" ;;
  cpu) asset="llama-${tag}-bin-ubuntu-x64.tar.gz" ;;
  *) echo "unknown backend '$BACKEND' (vulkan|cuda-12.8|cuda-13.4|rocm|cpu)" >&2; exit 2 ;;
esac

target="$DEST/llama-${tag}-${BACKEND}"
mkdir -p "$target"
echo "downloading $asset"
curl -fL --progress-bar -o "$target.tar.gz" "https://github.com/ggml-org/llama.cpp/releases/download/${tag}/${asset}"
tar xzf "$target.tar.gz" -C "$target" --strip-components=1
rm -f "$target.tar.gz"
"$target/llama-server" --list-devices
echo
echo "add to .env:"
echo "LLAMA_MODE=native"
echo "LLAMA_BIN=$target"

#!/usr/bin/env bash
# 从 hf-mirror 下载 all-MiniLM-L6-v2 的 INT8 ONNX 模型到 models/ 目录。
# 浏览器只读本地模型，避免受浏览器网络策略影响。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODEL="Xenova/all-MiniLM-L6-v2"
BASE="https://hf-mirror.com/${MODEL}/resolve/main"
DEST="models/${MODEL}"
mkdir -p "$DEST/onnx"

fetch() {
  local rel="$1"
  local url="${BASE}/${rel}"
  local out="${DEST}/${rel}"
  mkdir -p "$(dirname "$out")"
  if [[ -s "$out" ]]; then
    echo "  [skip] $rel"
    return 0
  fi
  if curl -sSL --fail -m 300 "$url" -o "$out"; then
    echo "  [ok]   $rel ($(du -h "$out" | cut -f1))"
    return 0
  fi
  rm -f "$out"
  echo "  [miss] $rel"
  return 1
}

echo "[model] 下载 $MODEL"
fetch config.json
fetch tokenizer.json
fetch tokenizer_config.json

# 量化权重可能有多种命名，按优先级尝试
fetch onnx/model_quantized.onnx || fetch onnx/model_q8.onnx || fetch onnx/model.onnx

echo
echo "[model] 结果"
du -sh "models" 2>/dev/null
find "$DEST" -type f | sort

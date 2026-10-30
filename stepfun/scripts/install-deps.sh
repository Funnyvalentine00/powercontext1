#!/usr/bin/env bash
# 安装依赖。
# 两个坑：
#   1) seekdb@1.4.0 的 npm 包内部使用 workspace: 协议，直接声明依赖会 EUNSUPPORTEDPROTOCOL，
#      且 npm install 会把不在 dependencies 里的包当作 extraneous 清掉，
#      所以 seekdb 必须最后从 tarball 手动装配；
#   2) @huggingface/transformers 的 onnxruntime-node 安装脚本要从 GitHub 下二进制（不可达），
#      浏览器只用 onnxruntime-web，用 --ignore-scripts 跳过。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"

mkdir -p node_modules

if [[ ! -d node_modules/mysql2 ]]; then
  echo "[deps] 安装 mysql2"
  npm install mysql2 --registry "$REGISTRY" --no-audit --no-fund
fi

if [[ ! -d node_modules/@huggingface/transformers ]]; then
  echo "[deps] 安装 @huggingface/transformers（--ignore-scripts）"
  npm install @huggingface/transformers --ignore-scripts --registry "$REGISTRY" --no-audit --no-fund
fi

# 必须放在所有 npm install 之后，否则会被当成 extraneous 清掉
echo "[deps] 装配 seekdb 1.4.0（绕过 workspace 协议）"
curl -sSL "https://registry.npmjs.org/seekdb/-/seekdb-1.4.0.tgz" -o /tmp/seekdb-1.4.0.tgz
rm -rf /tmp/seekdb-extract
mkdir -p /tmp/seekdb-extract
tar -xzf /tmp/seekdb-1.4.0.tgz -C /tmp/seekdb-extract
rm -rf node_modules/seekdb
cp -r /tmp/seekdb-extract/package node_modules/seekdb

echo
echo "[deps] 自检"
node -e 'const s = require("seekdb"); console.log("  seekdb:", typeof s.SeekdbClient === "function" ? "OK" : "FAIL");'
if [[ -f node_modules/@huggingface/transformers/dist/transformers.web.min.js ]]; then
  echo "  transformers: OK（web 构建存在）"
else
  echo "  transformers: 缺失"
fi
if ls node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.jsep.wasm >/dev/null 2>&1; then
  echo "  onnxruntime-web wasm: OK"
else
  echo "  onnxruntime-web wasm: 缺失"
fi

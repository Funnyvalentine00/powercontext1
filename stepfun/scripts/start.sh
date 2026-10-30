#!/usr/bin/env bash
# 一键启动：seekdb（若未运行）+ 应用服务
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bash scripts/start-seekdb.sh

echo "[app] 启动 Web 服务（Ctrl+C 退出）"
exec node server/index.js

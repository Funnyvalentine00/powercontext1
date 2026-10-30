#!/usr/bin/env bash
# 本地 WSL 开发环境准备：把 seekdb 数据目录挪到 WSL 原生 ext4。
#
# 原因：/mnt/d 是 drvfs 挂载，不支持 fallocate；seekdb 建库需要写 32MB 块文件，
# 会返回 EOPNOTSUPP。这是环境限制，与代码无关。
#
# 做法：在 .env（已被 .gitignore 排除）里写入两个路径覆盖项，由 cli.load_settings() 读取。
# 评测环境是原生 Linux，不需要执行本脚本。
#
# 用法:
#   bash scripts/dev-setup-wsl.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKING="${RCA_WSL_BACKING:-/var/lib/rca}"
cd "$ROOT"

mkdir -p "$BACKING/seekdb" "$BACKING/pc"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "[setup] 已从 .env.example 创建 .env"
  else
    : > .env
    echo "[setup] 已创建空 .env"
  fi
fi

ensure_line() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" .env; then
    echo "[setup] ${key} 已存在，保持不变"
  else
    printf '%s=%s\n' "$key" "$value" >> .env
    echo "[setup] 写入 ${key}=${value}"
  fi
}

ensure_line RCA_SEEKDB_PATH "$BACKING/seekdb"
ensure_line RCA_PC_HOME "$BACKING/pc"

echo
echo "[setup] 完成。数据目录："
ls -ld "$BACKING/seekdb" "$BACKING/pc"
echo "[setup] 语料仍在 data/corpus/（留在 Windows 盘上，可直接编辑）。"
echo "[setup] 接下来：bash run.sh ingest"

#!/usr/bin/env bash
# MiniMax SDD 上下文管理样例：reset | ingest | prepare | apply | test | all
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON=python3
  fi
fi

# .env 里可以写 POWERCONTEXT_SRC / POWERCONTEXT_VENV / MINIMAX_API_KEY 等。
if [[ -f "$ROOT/.env" ]]; then
  while IFS='=' read -r key value; do
    case "$key" in
      POWERCONTEXT_SRC|POWERCONTEXT_VENV|MINIMAX_API_KEY|MINIMAX_BASE_URL|MINIMAX_MODEL|DATABASE_KIND|POWERCONTEXT_PORT|POWERCONTEXT_URL)
        value="${value%%#*}"
        value="${value%\"}"; value="${value#\"}"
        value="${value%\'}"; value="${value#\'}"
        export "$key=$value"
        ;;
    esac
  done < "$ROOT/.env"
fi

if [[ -z "${POWERCONTEXT_SRC:-}" ]]; then
  if [[ -f "$ROOT/../src/powercontext/__init__.py" ]]; then
    POWERCONTEXT_SRC="$(cd "$ROOT/../src" && pwd)"
  elif [[ -f "$ROOT/.upstream/powercontext/src/powercontext/__init__.py" ]]; then
    POWERCONTEXT_SRC="$ROOT/.upstream/powercontext/src"
  else
    echo "未找到 PowerContext 源码：请先执行 bash bootstrap.sh（会拉取上游并安装依赖），" >&2
    echo "或设置 POWERCONTEXT_SRC 指向已检出的 powercontext/src 目录。" >&2
    exit 1
  fi
fi

export POWERCONTEXT_SRC
export PYTHONPATH="$ROOT:$POWERCONTEXT_SRC${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1

case "${1:-}" in
  start|stop|restart|status|reset|ingest|prepare|apply|test|db-inspect|all)
    exec "$PYTHON" -m sddsync.cli "$1"
    ;;
  verify)
    exec "$PYTHON" verify.py
    ;;
  *)
    cat <<'EOF'
用法: bash run.sh <命令>

命令:
  start      启动 PowerContext Server（默认 embedded seekdb，可用 DATABASE_KIND 切换）
  stop       停止 Server
  restart    重启 Server（用于验证状态复用）
  status     查看 Scope、Source、Memory 与任务状态
  reset      清空 data/ work/ logs/，样例工程回到必失败基线
  ingest     把规格/代码/测试写入 PowerContext Source（落到 seekdb）
  prepare    生成任务上下文 + Work Contract，并调用 MiniMax 产出补丁
  apply      从 PowerContext 恢复状态并把补丁应用到 work/app
  test       修改前（sample-app）与修改后（work/app）各跑一轮 pytest
  db-inspect 直连 embedded seekdb 执行真实 SQL，导出数据库取证材料
  all        reset -> start -> ingest -> prepare -> restart -> apply -> test -> db-inspect -> verify
  verify     执行 verify.py 的 6 项验收

首次使用请先执行: bash bootstrap.sh
（拉取上游 PowerContext 源码并安装依赖；幂等）
EOF
    exit 1
    ;;
esac

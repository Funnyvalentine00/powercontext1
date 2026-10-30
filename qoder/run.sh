#!/usr/bin/env bash
# 科研上下文助手：统一入口。所有子命令最终都落到 src/rca/cli.py。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

usage() {
  cat <<'EOF'
用法: bash run.sh <命令>

命令:
  start      后台启动 PowerContext Server（默认 embedded seekdb）
  stop       停止 Server
  restart    重启 Server（用于验证状态复用）
  serve      前台启动 Server（调试用）
  reset      清空 data/ work/ logs/
  ingest     把 data/corpus 下的文献切块写入 seekdb     [参数: 语料目录, 可选]
  ask        针对研究问题生成带证据与缺口的报告          [参数: "问题" --aspects a,b --task id]
  status     查看 PowerContext 中的研究任务状态          [参数: --task id]
  resume     从 PowerContext 读回任务状态与报告          [参数: 任务编号]
  verify     可核验自检（逐条回查证据 + 校验状态复用）
  test       跑单元测试
  all        reset -> ingest -> ask -> restart -> resume -> status -> verify

首次使用请先执行: bash bootstrap.sh
EOF
}

DEMO_QUESTION="${DEMO_QUESTION:-如何降低嵌入式数据库中文档检索的延迟}"
DEMO_ASPECTS="${DEMO_ASPECTS:-索引结构,检索延迟预算,分布式部署,GPU 加速}"

# 帮助不需要环境，先处理掉。
case "${1:-}" in
  ""|-h|--help|help)
    usage
    exit 0
    ;;
esac

if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON=python3
  fi
fi

# .env 里可以写 POWERCONTEXT_SRC / POWERCONTEXT_VENV / POWERCONTEXT_PORT 等。
if [[ -f "$ROOT/.env" ]]; then
  while IFS='=' read -r key value; do
    case "$key" in
      POWERCONTEXT_SRC|POWERCONTEXT_VENV|POWERCONTEXT_PORT|POWERCONTEXT_URL|DATABASE_KIND)
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
    echo "未找到 PowerContext 源码：请先执行 bash bootstrap.sh（会准备源码并安装依赖），" >&2
    echo "或设置 POWERCONTEXT_SRC 指向已检出的 powercontext/src 目录。" >&2
    exit 1
  fi
fi

export POWERCONTEXT_SRC
export PYTHONPATH="$ROOT/src:$POWERCONTEXT_SRC${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1

case "$1" in
  test)
    exec "$PYTHON" -m pytest -q tests
    ;;
  all)
    # 完整演示：清空 -> 入库 -> 提问 -> 重启 -> 复用状态 -> 查看 -> 自检
    "$PYTHON" -m rca.cli reset
    "$PYTHON" -m rca.cli ingest
    "$PYTHON" -m rca.cli ask "$DEMO_QUESTION" --aspects "$DEMO_ASPECTS" --task research-001
    "$PYTHON" -m rca.cli restart
    "$PYTHON" -m rca.cli resume research-001
    "$PYTHON" -m rca.cli status
    "$PYTHON" -m rca.cli verify
    ;;
  *)
    exec "$PYTHON" -m rca.cli "$@"
    ;;
esac

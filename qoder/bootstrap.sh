#!/usr/bin/env bash
# 自举：准备科研上下文助手的运行环境（幂等，可重复执行）。
#
# 参赛分支（2026-competition-ecosystem）只携带 qoder/ 资产，不含 PowerContext 源码，
# 因此需要先准备两样东西：
#   1) PowerContext 源码（优先从本仓库 2026-competition 分支 git archive 取出，不需要外网）
#   2) Python 虚拟环境与依赖（powercontext[server] + pylibseekdb + aiomysql + pytest + pyyaml）
#
# 用法:
#   bash bootstrap.sh
#   POWERCONTEXT_SRC=/path/to/powercontext/src bash bootstrap.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPSTREAM_URL="${POWERCONTEXT_UPSTREAM_URL:-https://github.com/oceanbase/powercontext.git}"
UPSTREAM_BRANCH="${POWERCONTEXT_UPSTREAM_BRANCH:-2026-competition}"
UPSTREAM_DIR="${POWERCONTEXT_UPSTREAM_DIR:-$ROOT/.upstream/powercontext}"
VENV_DIR="${POWERCONTEXT_VENV:-$ROOT/.venv}"

echo "[bootstrap] ===== 1/4 准备 PowerContext 源码 ====="
if [[ -n "${POWERCONTEXT_SRC:-}" && -f "$POWERCONTEXT_SRC/powercontext/__init__.py" ]]; then
  echo "[bootstrap]   使用环境变量指定的源码：$POWERCONTEXT_SRC"
elif [[ -f "$ROOT/../src/powercontext/__init__.py" ]]; then
  POWERCONTEXT_SRC="$(cd "$ROOT/../src" && pwd)"
  echo "[bootstrap]   使用同级仓库源码：$POWERCONTEXT_SRC"
elif [[ -f "$UPSTREAM_DIR/src/powercontext/__init__.py" ]]; then
  POWERCONTEXT_SRC="$UPSTREAM_DIR/src"
  echo "[bootstrap]   使用已就位的源码：$POWERCONTEXT_SRC"
else
  # 本仓库自身就有带 src/ 的 2026-competition 分支，优先从本地 git 历史里取（无需联网）。
  REPO_ROOT="$(cd "$ROOT/.." && pwd)"
  if [[ -d "$REPO_ROOT/.git" ]]; then
    BASE_REF=""
    for ref in origin/2026-competition 2026-competition origin/main main; do
      if git -C "$REPO_ROOT" rev-parse --verify --quiet "$ref^{tree}" >/dev/null 2>&1; then
        BASE_REF="$ref"
        break
      fi
    done
    if [[ -z "$BASE_REF" ]]; then
      echo "[bootstrap]   本地缺少含 src/ 的分支，尝试从 origin 拉取 2026-competition ..."
      git -C "$REPO_ROOT" fetch --depth 1 origin 2026-competition:refs/remotes/origin/2026-competition >/dev/null 2>&1 || true
      if git -C "$REPO_ROOT" rev-parse --verify --quiet "origin/2026-competition^{tree}" >/dev/null 2>&1; then
        BASE_REF="origin/2026-competition"
      fi
    fi
    if [[ -n "$BASE_REF" ]]; then
      echo "[bootstrap]   从本仓库分支 $BASE_REF 提取 src/ 与 pyproject.toml ..."
      mkdir -p "$UPSTREAM_DIR"
      if git -C "$REPO_ROOT" archive "$BASE_REF" src pyproject.toml README.md 2>/dev/null | tar -x -C "$UPSTREAM_DIR"; then
        POWERCONTEXT_SRC="$UPSTREAM_DIR/src"
      fi
      if [[ -f "${POWERCONTEXT_SRC:-}/powercontext/__init__.py" ]]; then
        echo "[bootstrap]   源码就绪：$POWERCONTEXT_SRC"
      else
        POWERCONTEXT_SRC=""
      fi
    fi
  fi
  if [[ ! -f "${POWERCONTEXT_SRC:-}/powercontext/__init__.py" ]]; then
    echo "[bootstrap]   本地 git 无可用源码，改为从 $UPSTREAM_URL 克隆分支 $UPSTREAM_BRANCH ..."
    rm -rf "$UPSTREAM_DIR"
    git clone --depth 1 --branch "$UPSTREAM_BRANCH" "$UPSTREAM_URL" "$UPSTREAM_DIR"
    POWERCONTEXT_SRC="$UPSTREAM_DIR/src"
    if [[ ! -f "$POWERCONTEXT_SRC/powercontext/__init__.py" ]]; then
      echo "[bootstrap]   错误：$UPSTREAM_BRANCH 分支不含 src/powercontext，请设置 POWERCONTEXT_SRC 指向源码目录" >&2
      exit 1
    fi
    echo "[bootstrap]   上游源码就绪：$POWERCONTEXT_SRC"
  fi
fi
export POWERCONTEXT_SRC

echo "[bootstrap] ===== 2/4 准备 Python 虚拟环境：$VENV_DIR ====="
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 "$VENV_DIR"
  else
    python3 -m venv "$VENV_DIR"
  fi
fi
PY="$VENV_DIR/bin/python"
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)'; then
  echo "[bootstrap]   错误：$PY 版本过低，PowerContext 需要 Python >= 3.11" >&2
  exit 1
fi
"$PY" --version

if "$PY" -m pip --version >/dev/null 2>&1; then
  INSTALL=("$PY" -m pip install --quiet)
elif command -v uv >/dev/null 2>&1; then
  INSTALL=(uv pip install --quiet --python "$PY")
else
  "$PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
  INSTALL=("$PY" -m pip install --quiet)
fi

echo "[bootstrap] ===== 3/4 安装依赖 ====="
install_root=""
probe="$POWERCONTEXT_SRC"
while [[ -n "$probe" && "$probe" != "/" ]]; do
  if [[ -f "$probe/pyproject.toml" ]]; then
    install_root="$probe"
    break
  fi
  probe="$(dirname "$probe")"
done

if ! "$PY" -c "import powercontext.server.factory" >/dev/null 2>&1; then
  echo "[bootstrap]   安装 PowerContext（server extra，含 uvicorn/fastapi/sqlalchemy 等）..."
  if [[ -n "$install_root" ]]; then
    if [[ -d "$install_root/.git" ]]; then
      "${INSTALL[@]}" -e "$install_root[server]"
    else
      SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 HATCH_VCS_PRETEND_VERSION=0.0.0 \
        "${INSTALL[@]}" -e "$install_root[server]"
    fi
  else
    "${INSTALL[@]}" "powercontext[server]"
  fi
fi

# pylibseekdb = embedded seekdb 引擎。pymysql 必须一起锁 <1.2.1：
# 1.2.1 起把 converters.escape_bytes_prefixed 换成哨兵字符串，而 aiomysql 0.3.2 仍在调用它，
# 写入 Source 时会报 "TypeError: 'str' object is not callable"。
if ! "$PY" -c "import pylibseekdb" >/dev/null 2>&1; then
  echo "[bootstrap]   安装 embedded seekdb（pylibseekdb）与 aiomysql..."
  "${INSTALL[@]}" "pylibseekdb>=1.4.0.post1,<2" "pymysql>=1.1,<1.2.1" aiomysql
fi
if ! "$PY" -c "import importlib.metadata as m; assert tuple(int(x) for x in m.version('pymysql').split('.')[:3]) < (1, 2, 1)" >/dev/null 2>&1; then
  echo "[bootstrap]   校正 pymysql 版本到 <1.2.1（1.2.1+ 与 aiomysql 0.3.2 不兼容）..."
  "${INSTALL[@]}" "pymysql>=1.1,<1.2.1"
fi
if ! "$PY" -c "import pytest, yaml" >/dev/null 2>&1; then
  echo "[bootstrap]   安装 pytest 与 pyyaml..."
  "${INSTALL[@]}" pytest pyyaml
fi

echo "[bootstrap] ===== 4/4 自检 ====="
PYTHONPATH="$POWERCONTEXT_SRC:$ROOT/src" "$PY" - <<'PY'
import importlib.metadata as m

for name in ("powercontext", "pylibseekdb", "pymysql", "aiomysql", "uvicorn", "fastapi", "sqlalchemy", "pytest", "pyyaml"):
    try:
        print(f"[bootstrap]   {name}=={m.version(name)}")
    except Exception:
        print(f"[bootstrap]   {name}: 未安装")

import rca  # noqa: F401
from powercontext.server.factory import create_server_app  # noqa: F401
from powercontext.server.settings import ServerSettings  # noqa: F401
print("[bootstrap]   PowerContext Server 依赖与 rca 包导入自检通过")
PY

cat <<EOF

[bootstrap] 完成。接下来：
  bash run.sh all
EOF

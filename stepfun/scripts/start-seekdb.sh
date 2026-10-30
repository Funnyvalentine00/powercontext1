#!/usr/bin/env bash
# 启动 seekdb（如果还没运行）。优先 systemd，其次直接拉起进程。
set -uo pipefail

PORT="${SEEKB_PORT:-2881}"
BASE="${SEEKB_BASE_DIR:-/var/lib/seekdb}"

probe() {
  python3 - "$PORT" <<'PY' 2>/dev/null
import socket, sys
port = int(sys.argv[1])
try:
    with socket.create_connection(("127.0.0.1", port), timeout=2):
        pass
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
}

if probe; then
  echo "[seekdb] 已在 ${PORT} 运行"
  exit 0
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl start seekdb >/dev/null 2>&1 || true
fi

for _ in $(seq 1 40); do
  if probe; then
    echo "[seekdb] 就绪（端口 ${PORT}）"
    exit 0
  fi
  sleep 1
done

echo "[seekdb] systemd 未就绪，尝试直接启动"
mkdir -p "$BASE"
setsid seekdb --nodaemon --port "$PORT" --base-dir "$BASE" > /tmp/seekdb.log 2>&1 < /dev/null &

for _ in $(seq 1 60); do
  if probe; then
    echo "[seekdb] 就绪（端口 ${PORT}，日志 /tmp/seekdb.log）"
    exit 0
  fi
  sleep 1
done

echo "[seekdb] 启动失败，请检查 /tmp/seekdb.log" >&2
exit 1

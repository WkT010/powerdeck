#!/usr/bin/env bash
# 启动 / 重启 web_log_viewer.py 的脚本。
set -e
cd "$(dirname "$0")"

PID_FILE="./.viewer.pid"
LOG_DIR="./output"
mkdir -p "$LOG_DIR"

# 1) 终止旧进程
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[start_viewer.sh] 终止旧 viewer PID=$OLD_PID"
        kill -TERM "$OLD_PID" 2>/dev/null || true
        sleep 1
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

# 2) 后台启动
PORT="${PORT:-8080}"
echo "[start_viewer.sh] 启动 web_log_viewer.py (PORT=$PORT) ..."
nohup env PORT="$PORT" python3 -u web_log_viewer.py >> "$LOG_DIR/viewer.log" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
sleep 1
echo "[start_viewer.sh] 已启动 PID=$NEW_PID，访问 http://<host>:$PORT/"

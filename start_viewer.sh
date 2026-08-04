#!/usr/bin/env bash
# viewer 启动脚本 — 后台运行，写 PID 到 .viewer.pid
set -e
cd /workspace

PIDFILE=".viewer.pid"

# 如果已在运行则退出
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if ps -p "$OLD_PID" -o pid= > /dev/null 2>&1; then
        echo "viewer already running PID=$OLD_PID"
        exit 0
    fi
fi

mkdir -p /workspace/output

export PORT=${PORT:-8080}
nohup python3 -u /workspace/web_log_viewer.py >> /workspace/output/viewer.log 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PIDFILE"
echo "viewer started PID=$NEW_PID"

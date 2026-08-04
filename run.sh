#!/usr/bin/env bash
# scanner 启动脚本 — 后台运行，写 PID 到 .scanner.pid
set -e
cd /workspace

PIDFILE=".scanner.pid"

# 如果已在运行则退出
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if ps -p "$OLD_PID" -o pid= > /dev/null 2>&1; then
        echo "scanner already running PID=$OLD_PID"
        exit 0
    fi
fi

mkdir -p /workspace/output

export SCAN_INTERVAL=${SCAN_INTERVAL:-0.3}
nohup python3 -u /workspace/scanner.py >> /workspace/output/scanner.log 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PIDFILE"
echo "scanner started PID=$NEW_PID"

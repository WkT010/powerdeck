#!/bin/bash
# scanner 启动脚本 - 管理 .scanner.pid
set -e
cd /workspace

# 杀掉旧进程（如果存在）
if [ -f .scanner.pid ]; then
    OLD_PID=$(cat .scanner.pid 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "scanner 已在运行 PID=$OLD_PID，先停止..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f .scanner.pid
fi

# 启动 scanner
export SCAN_INTERVAL=${SCAN_INTERVAL:-0.3}
nohup python3 /workspace/scanner.py >> /workspace/output/scanner.log 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > /workspace/.scanner.pid
echo "scanner 已启动 PID=$NEW_PID SCAN_INTERVAL=$SCAN_INTERVAL"

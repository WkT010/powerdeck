#!/usr/bin/env bash
# Scanner 启动脚本
set -e
cd /workspace

mkdir -p output

# 停止旧实例
if [ -f .scanner.pid ]; then
    OLD_PID=$(cat .scanner.pid)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping old scanner PID=$OLD_PID"
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f .scanner.pid
fi

# 启动
nohup python3 scanner.py >> output/scanner.log 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > .scanner.pid
echo "Scanner started PID=$NEW_PID"

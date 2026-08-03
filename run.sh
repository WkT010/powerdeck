#!/bin/bash
# Scanner 启动脚本
cd "$(dirname "$0")"

# 读取 SCAN_INTERVAL，默认 0.3
SCAN_INTERVAL="${SCAN_INTERVAL:-0.3}"
export SCAN_INTERVAL

# 清理旧 PID
if [ -f .scanner.pid ]; then
    OLD_PID=$(cat .scanner.pid 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null
        sleep 1
        kill -9 "$OLD_PID" 2>/dev/null
    fi
    rm -f .scanner.pid
fi

# 后台启动 scanner.py
if [ -f scanner.py ]; then
    nohup python3 -u scanner.py > output/scanner.log 2>&1 &
    echo $! > .scanner.pid
    echo "Scanner started PID=$(cat .scanner.pid)"
else
    # 占位：如果 scanner.py 不存在，用 sleep 模拟
    nohup bash -c "while true; do sleep 60; done" > output/scanner.log 2>&1 &
    echo $! > .scanner.pid
    echo "Scanner (placeholder) started PID=$(cat .scanner.pid)"
fi

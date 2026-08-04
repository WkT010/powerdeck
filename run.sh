#!/usr/bin/env bash
# Scanner 启动脚本 — 后台运行 scanner.py，PID 写入 .scanner.pid
set -euo pipefail
cd /workspace

# 杀掉旧进程（如果存在）
if [ -f .scanner.pid ]; then
    OLD_PID=$(cat .scanner.pid)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f .scanner.pid
fi

# 安装依赖（静默）
pip install -q aiohttp ecdsa 2>/dev/null || true

# 启动 scanner
export SCAN_INTERVAL="${SCAN_INTERVAL:-0.5}"
nohup python3 /workspace/scanner.py >> /workspace/output/scanner.log 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > /workspace/.scanner.pid
echo "scanner started PID=$NEW_PID"

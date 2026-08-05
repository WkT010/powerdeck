#!/bin/bash
# viewer 启动脚本 - 管理 .viewer.pid
set -e
cd /workspace

# 杀掉旧进程（如果存在）
if [ -f .viewer.pid ]; then
    OLD_PID=$(cat .viewer.pid 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "viewer 已在运行 PID=$OLD_PID，先停止..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f .viewer.pid
fi

# 启动 viewer
export PORT=${PORT:-8080}
nohup python3 /workspace/web_log_viewer.py >> /workspace/output/viewer.log 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > /workspace/.viewer.pid
echo "viewer 已启动 PID=$NEW_PID PORT=$PORT"

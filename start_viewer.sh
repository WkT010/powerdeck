#!/usr/bin/env bash
# Viewer 启动脚本
set -e
cd /workspace

mkdir -p output

# 停止旧实例
if [ -f .viewer.pid ]; then
    OLD_PID=$(cat .viewer.pid)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping old viewer PID=$OLD_PID"
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f .viewer.pid
fi

# 启动
nohup python3 web_log_viewer.py >> output/viewer.log 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > .viewer.pid
echo "Viewer started PID=$NEW_PID"

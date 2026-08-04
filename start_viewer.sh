#!/usr/bin/env bash
# Viewer 启动脚本 — 后台运行 web_log_viewer.py，PID 写入 .viewer.pid
set -euo pipefail
cd /workspace

# 杀掉旧进程（如果存在）
if [ -f .viewer.pid ]; then
    OLD_PID=$(cat .viewer.pid)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f .viewer.pid
fi

# 启动 viewer
export PORT="${PORT:-8080}"
nohup python3 /workspace/web_log_viewer.py >> /workspace/output/viewer.log 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > /workspace/.viewer.pid
echo "viewer started PID=$NEW_PID"

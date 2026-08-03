#!/bin/bash
# Web Log Viewer 启动脚本
cd "$(dirname "$0")"

# 读取 PORT，默认 8080
PORT="${PORT:-8080}"
export PORT

# 清理旧 PID
if [ -f .viewer.pid ]; then
    OLD_PID=$(cat .viewer.pid 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null
        sleep 1
        kill -9 "$OLD_PID" 2>/dev/null
    fi
    rm -f .viewer.pid
fi

# 后台启动 web_log_viewer.py
if [ -f web_log_viewer.py ]; then
    nohup python3 -u web_log_viewer.py > output/viewer.log 2>&1 &
    echo $! > .viewer.pid
    echo "Viewer started PID=$(cat .viewer.pid) on port $PORT"
else
    # 占位：如果 web_log_viewer.py 不存在，用 Python 自带的 http.server 模拟 8080 端口
    nohup python3 -m http.server "$PORT" --bind 0.0.0.0 > output/viewer.log 2>&1 &
    echo $! > .viewer.pid
    echo "Viewer (placeholder http.server) started PID=$(cat .viewer.pid) on port $PORT"
fi

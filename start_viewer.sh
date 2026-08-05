#!/bin/bash
# Web Log Viewer 启动脚本

set -e

cd /workspace

# 配置
PORT=${PORT:-8080}
HOST=${HOST:-0.0.0.0}
PID_FILE="/workspace/.viewer.pid"
LOG_FILE="/workspace/output/viewer.log"

# 创建输出目录
mkdir -p /workspace/output

# 检查是否已在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Viewer 已在运行 (PID: $PID)"
        exit 0
    else
        echo "清理旧的 PID 文件"
        rm -f "$PID_FILE"
    fi
fi

echo "启动 Web Log Viewer..."

# 启动 Python 脚本
nohup python3 web_log_viewer.py >> "$LOG_FILE" 2>&1 &
PID=$!

# 保存 PID
echo $PID > "$PID_FILE"

echo "Viewer 已启动 (PID: $PID)"
echo "访问地址: http://localhost:$PORT"
echo "日志文件: $LOG_FILE"

# 等待进程启动
sleep 2

# 检查进程是否存活
if ps -p "$PID" > /dev/null 2>&1; then
    echo "Viewer 运行正常"

    # 检查 HTTP 服务是否可用
    if command -v curl > /dev/null; then
        HTTP_CODE=$(curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            echo "HTTP 服务正常 (状态码: $HTTP_CODE)"
        else
            echo "警告: HTTP 服务可能未正常启动 (状态码: $HTTP_CODE)"
        fi
    fi
else
    echo "Viewer 启动失败，请检查日志"
    rm -f "$PID_FILE"
    exit 1
fi
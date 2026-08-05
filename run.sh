#!/bin/bash
# Scanner 启动脚本

set -e

cd /workspace

# 配置
SCAN_INTERVAL=${SCAN_INTERVAL:-0.3}
PID_FILE="/workspace/.scanner.pid"
LOG_FILE="/workspace/output/scanner.log"

# 创建输出目录
mkdir -p /workspace/output

# 检查是否已在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Scanner 已在运行 (PID: $PID)"
        exit 0
    else
        echo "清理旧的 PID 文件"
        rm -f "$PID_FILE"
    fi
fi

echo "启动 Scanner..."

# 启动 Python 脚本
nohup python3 scanner.py >> "$LOG_FILE" 2>&1 &
PID=$!

# 保存 PID
echo $PID > "$PID_FILE"

echo "Scanner 已启动 (PID: $PID)"
echo "日志文件: $LOG_FILE"

# 等待进程启动
sleep 2

# 检查进程是否存活
if ps -p "$PID" > /dev/null 2>&1; then
    echo "Scanner 运行正常"
else
    echo "Scanner 启动失败，请检查日志"
    rm -f "$PID_FILE"
    exit 1
fi
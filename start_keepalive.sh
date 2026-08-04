#!/bin/bash

# 启动保活任务守护进程
# 每小时执行一次 keepalive.sh

WORKSPACE="/workspace"
KEEPALIVE_SCRIPT="$WORKSPACE/keepalive.sh"
LOG_FILE="$WORKSPACE/output/keepalive.log"
PID_FILE="$WORKSPACE/.keepalive.pid"

# 创建输出目录
mkdir -p "$WORKSPACE/output"

# 检查是否已经在运行
if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE")
    if ps -p "$pid" > /dev/null 2>&1; then
        echo "保活任务已在运行中 (PID: $pid)"
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

echo "启动保活任务守护进程..."

# 启动后台循环
(
    while true; do
        # 执行保活检查
        echo "执行保活检查: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
        bash "$KEEPALIVE_SCRIPT" >> "$LOG_FILE" 2>&1
        
        # 等待1小时
        sleep 3600
    done
) &

# 保存PID
pid=$!
echo "$pid" > "$PID_FILE"

echo "保活任务守护进程已启动 (PID: $pid)"
echo "日志文件: $LOG_FILE"
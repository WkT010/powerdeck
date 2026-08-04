#!/bin/bash
# 启动双守护保活定时任务（每小时执行一次）

WORKSPACE="/workspace"
KEEPALIVE_SCRIPT="$WORKSPACE/keepalive.sh"
LOG_FILE="$WORKSPACE/output/keepalive.log"

# 确保 output 目录存在
mkdir -p "$WORKSPACE/output"

# 检查参数
INTERVAL=3600  # 默认每小时

if [ "$1" == "--once" ]; then
    echo "执行单次保活任务..."
    bash "$KEEPALIVE_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
    exit 0
fi

if [ -n "$1" ]; then
    INTERVAL=$1
fi

echo "========================================"  | tee -a "$LOG_FILE"
echo "启动双守护保活定时任务" | tee -a "$LOG_FILE"
echo "检查间隔: ${INTERVAL}秒 ($(($INTERVAL / 60))分钟)" | tee -a "$LOG_FILE"
echo "启动时间: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "日志文件: $LOG_FILE" | tee -a "$LOG_FILE"
echo "========================================"  | tee -a "$LOG_FILE"

# 循环执行
while true; do
    echo "" | tee -a "$LOG_FILE"
    bash "$KEEPALIVE_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    echo "下次执行: $(date -d "+${INTERVAL} seconds" '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
    sleep "$INTERVAL"
done
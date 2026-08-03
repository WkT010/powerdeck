#!/bin/bash
# 保活守护进程：每小时执行一次保活检查

LOG_FILE="/workspace/output/keepalive.log"
KEEPALIVE_SCRIPT="/workspace/keepalive.sh"

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 执行保活检查..." >> "$LOG_FILE"
    "$KEEPALIVE_SCRIPT" >> "$LOG_FILE" 2>&1
    echo "" >> "$LOG_FILE"
    
    # 等待 1 小时（3600 秒）
    sleep 3600
done
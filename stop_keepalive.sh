#!/bin/bash

# 停止保活任务守护进程

WORKSPACE="/workspace"
PID_FILE="$WORKSPACE/.keepalive.pid"

if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE")
    
    if ps -p "$pid" > /dev/null 2>&1; then
        kill "$pid"
        echo "保活任务已停止 (PID: $pid)"
    else
        echo "保活任务进程不存在"
    fi
    
    rm -f "$PID_FILE"
else
    echo "未找到保活任务PID文件"
fi
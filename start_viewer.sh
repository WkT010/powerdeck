#!/usr/bin/env bash
set -e
cd /workspace

PIDFILE=".viewer.pid"
LOGFILE="output/viewer.log"

mkdir -p output

# 如果已在运行则退出
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if ps -p "$OLD_PID" -o pid= > /dev/null 2>&1; then
        echo "viewer already running PID=$OLD_PID"
        exit 0
    fi
fi

echo "Starting viewer..."
nohup python3 web_log_viewer.py >> "$LOGFILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PIDFILE"
echo "viewer started PID=$NEW_PID"

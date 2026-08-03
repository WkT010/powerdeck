#!/bin/bash
# Viewer startup script

PID_FILE="/workspace/.viewer.pid"
LOG_FILE="/workspace/output/viewer.log"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Viewer already running (PID=$OLD_PID)"
        exit 0
    else
        echo "Stale PID file found, removing..."
        rm -f "$PID_FILE"
    fi
fi

cd /workspace
nohup python3 web_log_viewer.py >> "$LOG_FILE" 2>&1 &
VIEWER_PID=$!
echo "$VIEWER_PID" > "$PID_FILE"
echo "Viewer started (PID=$VIEWER_PID)"
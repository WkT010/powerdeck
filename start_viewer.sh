#!/bin/bash
# Viewer startup script
# Usage: bash start_viewer.sh

PID_FILE="/workspace/.viewer.pid"
LOG_FILE="/workspace/output/viewer.log"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Viewer already running (PID=$OLD_PID)"
        exit 0
    else
        echo "Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

mkdir -p /workspace/output
cd /workspace

export PYTHONUNBUFFERED=1
export PORT="${PORT:-8080}"

python3 web_log_viewer.py >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
echo "Viewer started (PID=$NEW_PID, PORT=$PORT)"

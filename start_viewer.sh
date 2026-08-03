#!/bin/bash
# Launcher for web_log_viewer.py — manages PID file
cd "$(dirname "$0")"

PID_FILE=".viewer.pid"
LOG_FILE="output/viewer.log"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Viewer already running (PID=$OLD_PID). Skipping."
        exit 0
    else
        echo "Removing stale PID $OLD_PID"
        rm -f "$PID_FILE"
    fi
fi

echo "Starting web viewer on port ${PORT:-8080}..."
nohup python3 web_log_viewer.py >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "Viewer started (PID=$(cat $PID_FILE))"

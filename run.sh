#!/bin/bash
# Launcher for scanner.py — manages PID file
cd "$(dirname "$0")"

PID_FILE=".scanner.pid"
LOG_FILE="output/scanner.log"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Scanner already running (PID=$OLD_PID). Skipping."
        exit 0
    else
        echo "Removing stale PID $OLD_PID"
        rm -f "$PID_FILE"
    fi
fi

echo "Starting scanner..."
nohup python3 scanner.py >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "Scanner started (PID=$(cat $PID_FILE))"

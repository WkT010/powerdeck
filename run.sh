#!/bin/bash
# Scanner startup script

PID_FILE="/workspace/.scanner.pid"
LOG_FILE="/workspace/output/scanner.log"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Scanner already running (PID=$OLD_PID)"
        exit 0
    else
        echo "Stale PID file found, removing..."
        rm -f "$PID_FILE"
    fi
fi

cd /workspace
nohup python3 scanner.py >> "$LOG_FILE" 2>&1 &
SCANNER_PID=$!
echo "$SCANNER_PID" > "$PID_FILE"
echo "Scanner started (PID=$SCANNER_PID)"
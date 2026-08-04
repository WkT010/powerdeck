#!/bin/bash
# Scanner startup script
# Usage: bash run.sh

PID_FILE="/workspace/.scanner.pid"
LOG_FILE="/workspace/output/scanner.log"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Scanner already running (PID=$OLD_PID)"
        exit 0
    else
        echo "Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

mkdir -p /workspace/output
cd /workspace

export PYTHONUNBUFFERED=1
export SCAN_INTERVAL="${SCAN_INTERVAL:-0.3}"

python3 scanner.py >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
echo "Scanner started (PID=$NEW_PID, SCAN_INTERVAL=$SCAN_INTERVAL)"

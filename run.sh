#!/bin/bash
set -euo pipefail

cd /workspace

PID_FILE="/workspace/.scanner.pid"
LOG_FILE="/workspace/output/scanner.log"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Scanner already running (PID=$OLD_PID)"
        exit 0
    fi
fi

mkdir -p /workspace/output

echo "[$(date -Iseconds)] Starting scanner..." >> "$LOG_FILE"

SCAN_INTERVAL="${SCAN_INTERVAL:-0.3}"

nohup python3 scanner.py >> "$LOG_FILE" 2>&1 &
SCANNER_PID=$!
echo "$SCANNER_PID" > "$PID_FILE"

echo "Scanner started (PID=$SCANNER_PID, SCAN_INTERVAL=$SCAN_INTERVAL)"
echo "[$(date -Iseconds)] Scanner started PID=$SCANNER_PID" >> "$LOG_FILE"

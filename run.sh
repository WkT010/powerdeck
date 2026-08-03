#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/.scanner.pid"
LOG_FILE="$SCRIPT_DIR/output/scanner.log"

export PYTHONUNBUFFERED=1

nohup python3 scanner.py >> "$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"
echo "Scanner started (PID=$PID)"

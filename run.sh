#!/bin/bash
# Scanner startup script

WORKSPACE="/workspace"
PID_FILE="$WORKSPACE/.scanner.pid"
OUTPUT_DIR="$WORKSPACE/output"
LOG_FILE="$OUTPUT_DIR/scanner.log"

mkdir -p "$OUTPUT_DIR"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Scanner already running (PID=$OLD_PID)"
        exit 0
    fi
fi

cd "$WORKSPACE"
nohup python3 scanner.py >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "Scanner started (PID=$(cat $PID_FILE))"

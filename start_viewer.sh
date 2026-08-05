#!/bin/bash
# Viewer startup script

WORKSPACE="/workspace"
PID_FILE="$WORKSPACE/.viewer.pid"
OUTPUT_DIR="$WORKSPACE/output"
LOG_FILE="$OUTPUT_DIR/viewer.log"
PORT="${PORT:-8080}"

mkdir -p "$OUTPUT_DIR"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Viewer already running (PID=$OLD_PID)"
        exit 0
    fi
fi

cd "$WORKSPACE"
PORT="$PORT" nohup python3 web_log_viewer.py >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "Viewer started (PID=$(cat $PID_FILE)) on port $PORT"

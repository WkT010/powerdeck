#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/.viewer.pid"
LOG_FILE="$SCRIPT_DIR/output/viewer.log"

export PYTHONUNBUFFERED=1

nohup python3 web_log_viewer.py >> "$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"
echo "Viewer started (PID=$PID, port=${PORT:-8080})"

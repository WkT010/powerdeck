#!/bin/bash
set -euo pipefail

cd /workspace

PID_FILE="/workspace/.viewer.pid"
LOG_FILE="/workspace/output/viewer.log"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Viewer already running (PID=$OLD_PID)"
        exit 0
    fi
fi

mkdir -p /workspace/output

echo "[$(date -Iseconds)] Starting web viewer..." >> "$LOG_FILE"

PORT="${PORT:-8080}"

nohup python3 web_log_viewer.py >> "$LOG_FILE" 2>&1 &
VIEWER_PID=$!
echo "$VIEWER_PID" > "$PID_FILE"

echo "Viewer started (PID=$VIEWER_PID, PORT=$PORT)"
echo "[$(date -Iseconds)] Viewer started PID=$VIEWER_PID PORT=$PORT" >> "$LOG_FILE"

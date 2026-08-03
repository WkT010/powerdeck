#!/bin/bash
# Web Log Viewer startup script with PID management
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.viewer.pid"
LOG_FILE="$SCRIPT_DIR/output/viewer.log"
PORT="${PORT:-8080}"

cd "$SCRIPT_DIR"

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Viewer already running with PID $OLD_PID on port $PORT"
        exit 0
    fi
fi

# Install dependencies if needed
pip install flask requests 2>/dev/null | tail -1

# Start viewer
echo "Starting web log viewer on port $PORT..."
PORT="$PORT" python3 web_log_viewer.py >> "$LOG_FILE" 2>&1 &
VIEWER_PID=$!
echo "$VIEWER_PID" > "$PID_FILE"

# Verify it started
sleep 2
if ps -p "$VIEWER_PID" > /dev/null 2>&1; then
    echo "Viewer started successfully, PID=$VIEWER_PID, port=$PORT"
else
    echo "ERROR: Viewer failed to start"
    rm -f "$PID_FILE"
    exit 1
fi

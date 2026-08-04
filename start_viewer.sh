#!/bin/bash
# Viewer startup script - manages .viewer.pid

WORKSPACE="/workspace"
PID_FILE="$WORKSPACE/.viewer.pid"
VIEWER="$WORKSPACE/web_log_viewer.py"
OUTPUT_DIR="$WORKSPACE/output"

mkdir -p "$OUTPUT_DIR"

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Viewer already running (PID=$OLD_PID)"
        exit 0
    else
        echo "Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

# Start viewer
cd "$WORKSPACE"
python3 "$VIEWER" >> "$OUTPUT_DIR/viewer.log" 2>&1 &
VIEWER_PID=$!
echo "$VIEWER_PID" > "$PID_FILE"
echo "Viewer started (PID=$VIEWER_PID)"

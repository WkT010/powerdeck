#!/bin/bash
# Launcher for web_log_viewer.py — writes PID and keeps it running
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$BASE_DIR/.viewer.pid"
LOG_DIR="$BASE_DIR/output"

mkdir -p "$LOG_DIR"

# Check for existing process
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Viewer already running (PID=$OLD_PID)"
        exit 0
    fi
fi

# Install dependencies if needed
if ! python3 -c "import flask" 2>/dev/null; then
    echo "Installing flask..."
    pip3 install -q flask 2>/dev/null || pip install -q flask 2>/dev/null
fi

# Start viewer
cd "$BASE_DIR"
nohup python3 -u web_log_viewer.py >> "$LOG_DIR/viewer.log" 2>&1 &
VIEWER_PID=$!
echo "$VIEWER_PID" > "$PID_FILE"
echo "Viewer started (PID=$VIEWER_PID)"

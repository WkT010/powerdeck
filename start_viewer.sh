#!/bin/bash
cd /workspace

# Kill existing viewer if running
if [ -f .viewer.pid ]; then
    OLD_PID=$(cat .viewer.pid 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null
        sleep 1
    fi
    rm -f .viewer.pid
fi

# Start viewer in background
python3 web_log_viewer.py &
VIEWER_PID=$!
echo "$VIEWER_PID" > .viewer.pid

# Wait a moment for process to start
sleep 1

# Verify it's running
if kill -0 "$VIEWER_PID" 2>/dev/null; then
    echo "Viewer started successfully with PID=$VIEWER_PID"
else
    echo "ERROR: Viewer failed to start"
    rm -f .viewer.pid
    exit 1
fi

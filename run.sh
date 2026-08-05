#!/bin/bash
cd /workspace

# Kill existing scanner if running
if [ -f .scanner.pid ]; then
    OLD_PID=$(cat .scanner.pid 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null
        sleep 1
    fi
    rm -f .scanner.pid
fi

# Start scanner in background
python3 scanner.py &
SCANNER_PID=$!
echo "$SCANNER_PID" > .scanner.pid

# Wait a moment for process to start
sleep 1

# Verify it's running
if kill -0 "$SCANNER_PID" 2>/dev/null; then
    echo "Scanner started successfully with PID=$SCANNER_PID"
else
    echo "ERROR: Scanner failed to start"
    rm -f .scanner.pid
    exit 1
fi

#!/bin/bash
# Launcher for scanner.py — writes PID and keeps it running
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$BASE_DIR/.scanner.pid"
LOG_DIR="$BASE_DIR/output"

mkdir -p "$LOG_DIR"

# Check for existing process
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Scanner already running (PID=$OLD_PID)"
        exit 0
    fi
fi

# Install dependencies if needed
if ! python3 -c "import ecdsa, eth_utils, requests, flask" 2>/dev/null; then
    echo "Installing dependencies..."
    pip3 install -q -r "$BASE_DIR/requirements.txt" 2>/dev/null || pip install -q -r "$BASE_DIR/requirements.txt" 2>/dev/null
fi

# Start scanner
cd "$BASE_DIR"
nohup python3 -u scanner.py >> "$LOG_DIR/scanner.log" 2>&1 &
SCANNER_PID=$!
echo "$SCANNER_PID" > "$PID_FILE"
echo "Scanner started (PID=$SCANNER_PID)"

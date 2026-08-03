#!/bin/bash
# Scanner startup script with PID management
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.scanner.pid"
LOG_FILE="$SCRIPT_DIR/output/scanner.log"

cd "$SCRIPT_DIR"

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Scanner already running with PID $OLD_PID"
        exit 0
    fi
fi

# Install dependencies if needed
pip install flask requests web3 eth_account pycryptodome 2>/dev/null | tail -1

# Start scanner
echo "Starting scanner..."
python3 scanner.py >> "$LOG_FILE" 2>&1 &
SCANNER_PID=$!
echo "$SCANNER_PID" > "$PID_FILE"

# Verify it started
sleep 2
if ps -p "$SCANNER_PID" > /dev/null 2>&1; then
    echo "Scanner started successfully, PID=$SCANNER_PID"
else
    echo "ERROR: Scanner failed to start"
    rm -f "$PID_FILE"
    exit 1
fi

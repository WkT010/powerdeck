#!/bin/bash
# Scanner startup script - manages .scanner.pid

WORKSPACE="/workspace"
PID_FILE="$WORKSPACE/.scanner.pid"
SCANNER="$WORKSPACE/scanner.py"
OUTPUT_DIR="$WORKSPACE/output"

mkdir -p "$OUTPUT_DIR"

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Scanner already running (PID=$OLD_PID)"
        exit 0
    else
        echo "Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

# Start scanner
cd "$WORKSPACE"
python3 "$SCANNER" >> "$OUTPUT_DIR/scanner.log" 2>&1 &
SCANNER_PID=$!
echo "$SCANNER_PID" > "$PID_FILE"
echo "Scanner started (PID=$SCANNER_PID)"

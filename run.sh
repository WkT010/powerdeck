#!/usr/bin/env bash
set -e
cd /workspace

PIDFILE=".scanner.pid"
LOGFILE="output/scanner.log"

mkdir -p output

# 如果已在运行则退出
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if ps -p "$OLD_PID" -o pid= > /dev/null 2>&1; then
        echo "scanner already running PID=$OLD_PID"
        exit 0
    fi
fi

echo "Starting scanner..."
nohup python3 scanner.py >> "$LOGFILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PIDFILE"
echo "scanner started PID=$NEW_PID"

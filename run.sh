#!/usr/bin/env bash
# 启动 / 重启 scanner.py 的保活脚本。
# - 若已有进程在运行，先优雅 kill 再启动。
# - 日志输出到 output/scanner.log（同时 stdout）。
set -e

cd "$(dirname "$0")"

PID_FILE="./.scanner.pid"
LOG_DIR="./output"
mkdir -p "$LOG_DIR"

# 1) 终止旧进程
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[run.sh] 终止旧进程 PID=$OLD_PID"
        kill -TERM "$OLD_PID" 2>/dev/null || true
        sleep 2
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

# 2) 确保依赖
if ! python3 -c "import web3, requests" 2>/dev/null; then
    echo "[run.sh] 安装依赖..."
    pip3 install -q -r requirements.txt
fi

# 3) 后台启动
echo "[run.sh] 启动 scanner.py ..."
nohup python3 -u scanner.py >> "$LOG_DIR/scanner.stdout.log" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
echo "[run.sh] 已启动 PID=$NEW_PID，日志: $LOG_DIR/scanner.log"

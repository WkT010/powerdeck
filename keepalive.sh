#!/usr/bin/env bash
# ============================================================================
# keepalive.sh — 双守护保活脚本
# 每小时（或手动执行）检查 scanner.py 与 web_log_viewer.py 是否运行，
# 未运行则重启，并输出结构化报告。
# ============================================================================
set -euo pipefail

BASE="/workspace"
OUTPUT_DIR="$BASE/output"
FAIL_FILE="$OUTPUT_DIR/keepalive_failures"
HOSTNAME_VAL=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")

mkdir -p "$OUTPUT_DIR"

# ---------- 辅助函数 ----------
is_alive() {
    local pid_file="$1"
    if [ ! -f "$pid_file" ]; then
        return 1
    fi
    local pid
    pid=$(cat "$pid_file" 2>/dev/null || echo "")
    if [ -z "$pid" ]; then
        return 1
    fi
    # 检查进程是否存在
    if ps -p "$pid" -o etime= >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

get_etime() {
    local pid="$1"
    ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ' || echo "0"
}

get_pid() {
    local pid_file="$1"
    cat "$pid_file" 2>/dev/null || echo ""
}

increment_failures() {
    local count=0
    if [ -f "$FAIL_FILE" ]; then
        count=$(cat "$FAIL_FILE" 2>/dev/null || echo "0")
    fi
    count=$((count + 1))
    echo "$count" > "$FAIL_FILE"
}

reset_failures() {
    echo "0" > "$FAIL_FILE"
}

get_failures() {
    if [ -f "$FAIL_FILE" ]; then
        cat "$FAIL_FILE" 2>/dev/null || echo "0"
    else
        echo "0"
    fi
}

# ---------- 1. 检查 scanner ----------
SCANNER_STATUS=""
SCANNER_RESTARTED=false

if is_alive "$BASE/.scanner.pid"; then
    SCANNER_PID=$(get_pid "$BASE/.scanner.pid")
    SCANNER_ETIME=$(get_etime "$SCANNER_PID")
    SCANNER_STATUS="scanner: 运行中 PID=$SCANNER_PID 已运行=$SCANNER_ETIME"
else
    echo "[keepalive] scanner 未运行，正在重启..."
    cd "$BASE"
    SCAN_INTERVAL=0.3 bash run.sh
    sleep 10  # 等待 benchmark 完成
    if is_alive "$BASE/.scanner.pid"; then
        SCANNER_PID=$(get_pid "$BASE/.scanner.pid")
        SCANNER_STATUS="scanner: 已重启 PID=$SCANNER_PID"
        SCANNER_RESTARTED=true
    else
        SCANNER_STATUS="scanner: 重启失败!"
        SCANNER_PID=""
    fi
fi

# ---------- 2. 检查 viewer ----------
VIEWER_STATUS=""
VIEWER_RESTARTED=false

if is_alive "$BASE/.viewer.pid"; then
    VIEWER_PID=$(get_pid "$BASE/.viewer.pid")
    VIEWER_ETIME=$(get_etime "$VIEWER_PID")
    VIEWER_STATUS="viewer: 运行中 PID=$VIEWER_PID 已运行=$VIEWER_ETIME 访问 http://$HOSTNAME_VAL:8080/"
else
    echo "[keepalive] viewer 未运行，正在重启..."
    cd "$BASE"
    PORT=8080 bash start_viewer.sh
    sleep 2
    # 验证 HTTP 200
    HTTP_CODE=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null || echo "000")
    if is_alive "$BASE/.viewer.pid" && [ "$HTTP_CODE" = "200" ]; then
        VIEWER_PID=$(get_pid "$BASE/.viewer.pid")
        VIEWER_STATUS="viewer: 已重启 PID=$VIEWER_PID 访问 http://$HOSTNAME_VAL:8080/"
        VIEWER_RESTARTED=true
    else
        VIEWER_PID=$(get_pid "$BASE/.viewer.pid" 2>/dev/null || echo "")
        if [ -n "$VIEWER_PID" ] && is_alive "$BASE/.viewer.pid"; then
            VIEWER_STATUS="viewer: 已重启 PID=$VIEWER_PID 但 HTTP 返回 $HTTP_CODE 访问 http://$HOSTNAME_VAL:8080/"
            VIEWER_RESTARTED=true
        else
            VIEWER_STATUS="viewer: 重启失败! (HTTP=$HTTP_CODE)"
        fi
    fi
fi

# ---------- 3. 读取速度指标 ----------
STATS_FILE="$OUTPUT_DIR/stats.json"
SCAN_RATE_TOTAL="N/A"
SCAN_RATE_RECENT="N/A"
KEYGEN_RATE="N/A"
TOTAL_SCANNED="N/A"
TOTAL_HITS="N/A"
TOTAL_RUNNING="N/A"

if [ -f "$STATS_FILE" ]; then
    SCAN_RATE_TOTAL=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('scan_rate_total_addr_per_sec','N/A'))" 2>/dev/null || echo "N/A")
    SCAN_RATE_RECENT=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('scan_rate_recent_addr_per_sec','N/A'))" 2>/dev/null || echo "N/A")
    KEYGEN_RATE=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('keygen_rate_keys_per_sec','N/A'))" 2>/dev/null || echo "N/A")
    TOTAL_SCANNED=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('total_scanned','N/A'))" 2>/dev/null || echo "N/A")
    TOTAL_HITS=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('total_hits','N/A'))" 2>/dev/null || echo "N/A")
    TOTAL_RUNNING=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('total_running_sec','N/A'))" 2>/dev/null || echo "N/A")
fi

# ---------- 5. 连续失败计数 ----------
if $SCANNER_RESTARTED || $VIEWER_RESTARTED; then
    # 判断是否真正拉起失败
    SCANNER_FAIL=false
    VIEWER_FAIL=false
    if echo "$SCANNER_STATUS" | grep -q "重启失败"; then
        SCANNER_FAIL=true
    fi
    if echo "$VIEWER_STATUS" | grep -q "重启失败"; then
        VIEWER_FAIL=true
    fi
    if $SCANNER_FAIL || $VIEWER_FAIL; then
        increment_failures
    else
        # 重启成功了，重置
        reset_failures
    fi
else
    # 都没重启，说明都在正常运行
    reset_failures
fi

FAIL_COUNT=$(get_failures)

# ---------- 4. 输出结构化报告 ----------
echo "=========================================="
echo "  保活检查报告 — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
echo ""
echo "$SCANNER_STATUS"
echo "$VIEWER_STATUS"
echo ""
echo "扫描速度(全程)=${SCAN_RATE_TOTAL} addr/s，扫描速度(近30)=${SCAN_RATE_RECENT} addr/s，计算速度=${KEYGEN_RATE} keys/s"
echo "累计扫描=${TOTAL_SCANNED}，命中=${TOTAL_HITS}，本次运行=${TOTAL_RUNNING}s"
echo ""

# ---------- 连续失败告警 ----------
if [ "$FAIL_COUNT" -ge 3 ]; then
    echo "⚠ 连续失败 ${FAIL_COUNT} 次，可能依赖或 RPC 出问题！"
    echo ""
    echo "--- scanner.log 末尾 20 行 ---"
    if [ -f "$OUTPUT_DIR/scanner.log" ]; then
        tail -20 "$OUTPUT_DIR/scanner.log" 2>/dev/null || echo "(无法读取)"
    else
        echo "(文件不存在)"
    fi
    echo ""
    echo "--- viewer.log 末尾 10 行 ---"
    if [ -f "$OUTPUT_DIR/viewer.log" ]; then
        tail -10 "$OUTPUT_DIR/viewer.log" 2>/dev/null || echo "(无法读取)"
    else
        echo "(文件不存在)"
    fi
fi

echo "=========================================="

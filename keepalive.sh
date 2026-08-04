#!/bin/bash
set -u

WORKSPACE="/workspace"
OUTPUT_DIR="${WORKSPACE}/output"
SCANNER_PID_FILE="${WORKSPACE}/.scanner.pid"
VIEWER_PID_FILE="${WORKSPACE}/.viewer.pid"
STATS_FILE="${OUTPUT_DIR}/stats.json"
FAILURES_FILE="${OUTPUT_DIR}/keepalive_failures"
SCANNER_LOG="${OUTPUT_DIR}/scanner.log"
VIEWER_LOG="${OUTPUT_DIR}/viewer.log"

SCANNER_RESTARTED=0
VIEWER_RESTARTED=0
SCANNER_FAILED=0
VIEWER_FAILED=0

SCANNER_STATUS_LINE=""
VIEWER_STATUS_LINE=""

get_host_ip() {
    local ip
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [ -z "$ip" ]; then
        ip="127.0.0.1"
    fi
    echo "$ip"
}

check_process_alive() {
    local pid="$1"
    if [ -z "$pid" ]; then
        return 1
    fi
    if ps -p "$pid" -o etime= >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

get_process_etime() {
    local pid="$1"
    ps -p "$pid" -o etime= 2>/dev/null | tr -d ' '
}

read_pid_file() {
    local file="$1"
    if [ -f "$file" ]; then
        tr -d '[:space:]' < "$file"
    fi
}

# ============ 1. 检查 scanner ============
SCANNER_PID=$(read_pid_file "$SCANNER_PID_FILE")

if check_process_alive "$SCANNER_PID"; then
    ETIME=$(get_process_etime "$SCANNER_PID")
    SCANNER_STATUS_LINE="scanner: 运行中 PID=${SCANNER_PID} 已运行=${ETIME}"
else
    # 未运行，尝试重启
    if [ -f "${WORKSPACE}/run.sh" ]; then
        (cd "$WORKSPACE" && SCAN_INTERVAL=0.3 bash run.sh >/dev/null 2>&1 &)
        sleep 10
        NEW_PID=$(read_pid_file "$SCANNER_PID_FILE")
        if check_process_alive "$NEW_PID"; then
            SCANNER_RESTARTED=1
            SCANNER_STATUS_LINE="scanner: 已重启 PID=${NEW_PID}"
        else
            SCANNER_FAILED=1
            SCANNER_STATUS_LINE="scanner: 重启失败 PID文件=${SCANNER_PID_FILE:-缺失} 进程未存活"
        fi
    else
        SCANNER_FAILED=1
        SCANNER_STATUS_LINE="scanner: 启动脚本缺失 ${WORKSPACE}/run.sh 不存在"
    fi
fi

# ============ 2. 检查 viewer ============
VIEWER_PID=$(read_pid_file "$VIEWER_PID_FILE")
HOST_IP=$(get_host_ip)

if check_process_alive "$VIEWER_PID"; then
    ETIME=$(get_process_etime "$VIEWER_PID")
    VIEWER_STATUS_LINE="viewer: 运行中 PID=${VIEWER_PID} 已运行=${ETIME} 访问 http://${HOST_IP}:8080/"
else
    # 未运行，尝试重启
    if [ -f "${WORKSPACE}/start_viewer.sh" ]; then
        (cd "$WORKSPACE" && PORT=8080 bash start_viewer.sh >/dev/null 2>&1 &)
        sleep 2
        NEW_PID=$(read_pid_file "$VIEWER_PID_FILE")
        HTTP_CODE=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null)
        HTTP_CODE=${HTTP_CODE:-000}
        if check_process_alive "$NEW_PID" && [ "$HTTP_CODE" = "200" ]; then
            VIEWER_RESTARTED=1
            VIEWER_STATUS_LINE="viewer: 已重启 PID=${NEW_PID} 访问 http://${HOST_IP}:8080/"
        else
            VIEWER_FAILED=1
            VIEWER_STATUS_LINE="viewer: 重启失败 PID=${NEW_PID:-缺失} HTTP=${HTTP_CODE}"
        fi
    else
        # 即使脚本缺失，也尝试 curl 检查（可能已有外部启动）
        HTTP_CODE=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null)
        HTTP_CODE=${HTTP_CODE:-000}
        if [ "$HTTP_CODE" = "200" ]; then
            VIEWER_STATUS_LINE="viewer: 运行中(脚本缺失但服务可用) 访问 http://${HOST_IP}:8080/"
        else
            VIEWER_FAILED=1
            VIEWER_STATUS_LINE="viewer: 启动脚本缺失 ${WORKSPACE}/start_viewer.sh 不存在，HTTP=${HTTP_CODE}"
        fi
    fi
fi

# ============ 3. 读取 stats.json ============
SCAN_RATE_TOTAL="N/A"
SCAN_RATE_RECENT="N/A"
KEYGEN_RATE="N/A"
SCANNED_COUNT="N/A"
HITS_COUNT="N/A"
TOTAL_RUNNING_SEC="N/A"

if [ -f "$STATS_FILE" ]; then
    # 用 python 解析 json，避免依赖 jq
    PARSED=$(python3 -c "
import json, sys
try:
    with open('$STATS_FILE', 'r') as f:
        d = json.load(f)
    def g(k, alt='N/A'):
        v = d.get(k, alt)
        if v is None: return alt
        return v
    # 扫描速度全程
    t = g('scan_rate_total_addr_per_sec', None)
    if t is None:
        # 兼容别名
        t = g('scan_rate_total', None)
    if t is None:
        # 从 scanned / running_sec 推导
        sc = d.get('scanned', 0)
        rs = d.get('total_running_sec', 0) or d.get('running_sec', 0) or 1
        t = round(sc / rs, 2) if rs > 0 else 0
    # 扫描速度近30
    r = g('scan_rate_recent_addr_per_sec', None)
    if r is None:
        r = g('scan_rate_recent_30s', g('scan_rate_recent', t))
    # 计算速度
    k = g('keygen_rate_keys_per_sec', None)
    if k is None:
        k = g('keygen_rate', g('calc_rate', 'N/A'))
    sc = g('scanned', g('total_scanned', 'N/A'))
    ht = g('hits', g('found', g('hit_count', 'N/A')))
    trs = g('total_running_sec', g('running_sec', 'N/A'))
    print(f'{t}|{r}|{k}|{sc}|{ht}|{trs}')
except Exception as e:
    print(f'ERR|{e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null) || PARSED=""
    if [ -n "$PARSED" ] && [[ "$PARSED" != ERR* ]]; then
        IFS='|' read -r SCAN_RATE_TOTAL SCAN_RATE_RECENT KEYGEN_RATE SCANNED_COUNT HITS_COUNT TOTAL_RUNNING_SEC <<< "$PARSED"
    fi
fi

# 格式化数字：如果是数字，保留2位小数
fmt_num() {
    local v="$1"
    if [[ "$v" =~ ^-?[0-9]+\.?[0-9]*$ ]]; then
        printf "%.2f" "$v"
    else
        echo "$v"
    fi
}
fmt_int() {
    local v="$1"
    if [[ "$v" =~ ^-?[0-9]+$ ]]; then
        printf "%d" "$v"
    else
        echo "$v"
    fi
}

SCAN_RATE_TOTAL_F=$(fmt_num "$SCAN_RATE_TOTAL")
SCAN_RATE_RECENT_F=$(fmt_num "$SCAN_RATE_RECENT")
KEYGEN_RATE_F=$(fmt_num "$KEYGEN_RATE")
SCANNED_COUNT_F=$(fmt_int "$SCANNED_COUNT")
HITS_COUNT_F=$(fmt_int "$HITS_COUNT")
TOTAL_RUNNING_SEC_F=$(fmt_num "$TOTAL_RUNNING_SEC")

# ============ 5. 连续失败计数 ============
FAIL_COUNT=0
if [ -f "$FAILURES_FILE" ]; then
    FC=$(tr -d '[:space:]' < "$FAILURES_FILE")
    if [[ "$FC" =~ ^[0-9]+$ ]]; then
        FAIL_COUNT=$FC
    fi
fi

if [ "$SCANNER_FAILED" -eq 1 ] || [ "$VIEWER_FAILED" -eq 1 ]; then
    FAIL_COUNT=$((FAIL_COUNT + 1))
else
    FAIL_COUNT=0
fi
echo "$FAIL_COUNT" > "$FAILURES_FILE"

# ============ 4. 输出结构化报告 ============
echo "============================================================"
echo "            双守护保活报告 $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo "$SCANNER_STATUS_LINE"
echo "$VIEWER_STATUS_LINE"
echo "------------------------------------------------------------"
echo "扫描速度(全程)=${SCAN_RATE_TOTAL_F} addr/s，扫描速度(近30)=${SCAN_RATE_RECENT_F} addr/s，计算速度=${KEYGEN_RATE_F} keys/s"
echo "累计扫描=${SCANNED_COUNT_F}，命中=${HITS_COUNT_F}，本次运行=${TOTAL_RUNNING_SEC_F}s"
echo "------------------------------------------------------------"
echo "连续失败计数=${FAIL_COUNT}"

if [ "$FAIL_COUNT" -ge 3 ]; then
    echo "============================================================"
    echo "⚠️  连续失败(${FAIL_COUNT}次)，可能依赖或 RPC 出问题"
    echo "============================================================"
    if [ -f "$SCANNER_LOG" ]; then
        echo ""
        echo "--- scanner.log 末尾 20 行 ---"
        tail -n 20 "$SCANNER_LOG" 2>/dev/null || echo "(无法读取)"
    else
        echo "scanner.log 不存在: $SCANNER_LOG"
    fi
    if [ -f "$VIEWER_LOG" ]; then
        echo ""
        echo "--- viewer.log 末尾 10 行 ---"
        tail -n 10 "$VIEWER_LOG" 2>/dev/null || echo "(无法读取)"
    else
        echo "viewer.log 不存在: $VIEWER_LOG"
    fi
fi

echo "============================================================"

# 以失败码退出便于 cron 监控
if [ "$SCANNER_FAILED" -eq 1 ] || [ "$VIEWER_FAILED" -eq 1 ]; then
    exit 1
fi
exit 0

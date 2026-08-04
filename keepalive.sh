#!/usr/bin/env bash
set -euo pipefail

WORKSPACE=/workspace
OUTPUT_DIR=$WORKSPACE/output
FAILURE_FILE=$OUTPUT_DIR/keepalive_failures
STATS_FILE=$OUTPUT_DIR/stats.json

# 获取本机 IP（优先非回环地址）
get_host_ip() {
    local ip
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [[ -z "$ip" ]]; then
        ip=$(ip route get 1 2>/dev/null | awk '{print $7; exit}')
    fi
    if [[ -z "$ip" ]]; then
        ip="127.0.0.1"
    fi
    echo "$ip"
}

HOST_IP=$(get_host_ip)

# 读取失败计数
failures=0
if [[ -f $FAILURE_FILE ]]; then
    failures=$(cat "$FAILURE_FILE" | tr -d '[:space:]' || true)
    if ! [[ "$failures" =~ ^[0-9]+$ ]]; then
        failures=0
    fi
fi

scanner_failed=false
viewer_failed=false

# =====================
# 1. 检查 scanner
# =====================
scanner_status=""
scanner_pid=""
scanner_etime=""
scanner_needs_restart=false

if [[ -f $WORKSPACE/.scanner.pid ]]; then
    scanner_pid=$(cat "$WORKSPACE/.scanner.pid" | tr -d '[:space:]')
    if [[ -n "$scanner_pid" ]] && ps -p "$scanner_pid" -o etime= >/dev/null 2>&1; then
        scanner_etime=$(ps -p "$scanner_pid" -o etime= | head -n1 | tr -d '[:space:]')
        scanner_status="scanner: 运行中 PID=$scanner_pid 已运行=$scanner_etime"
    else
        scanner_needs_restart=true
    fi
else
    scanner_needs_restart=true
fi

if $scanner_needs_restart; then
    cd "$WORKSPACE" && SCAN_INTERVAL=0.3 bash run.sh >/dev/null 2>&1 &
    sleep 10
    if [[ -f $WORKSPACE/.scanner.pid ]]; then
        scanner_pid=$(cat "$WORKSPACE/.scanner.pid" | tr -d '[:space:]')
        if [[ -n "$scanner_pid" ]] && ps -p "$scanner_pid" -o etime= >/dev/null 2>&1; then
            scanner_status="scanner: 已重启 PID=$scanner_pid"
        else
            scanner_status="scanner: 重启失败"
            scanner_failed=true
        fi
    else
        scanner_status="scanner: 重启失败（未生成 PID 文件）"
        scanner_failed=true
    fi
fi

# =====================
# 2. 检查 viewer
# =====================
viewer_status=""
viewer_pid=""
viewer_etime=""
viewer_needs_restart=false

if [[ -f $WORKSPACE/.viewer.pid ]]; then
    viewer_pid=$(cat "$WORKSPACE/.viewer.pid" | tr -d '[:space:]')
    if [[ -n "$viewer_pid" ]] && ps -p "$viewer_pid" -o etime= >/dev/null 2>&1; then
        viewer_etime=$(ps -p "$viewer_pid" -o etime= | head -n1 | tr -d '[:space:]')
        viewer_status="viewer: 运行中 PID=$viewer_pid 已运行=$viewer_etime 访问 http://$HOST_IP:8080/"
    else
        viewer_needs_restart=true
    fi
else
    viewer_needs_restart=true
fi

if $viewer_needs_restart; then
    cd "$WORKSPACE" && PORT=8080 bash start_viewer.sh >/dev/null 2>&1 &
    sleep 2
    if [[ -f $WORKSPACE/.viewer.pid ]]; then
        viewer_pid=$(cat "$WORKSPACE/.viewer.pid" | tr -d '[:space:]')
        http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:8080/" 2>/dev/null || true)
        if [[ "$http_code" == "200" ]]; then
            viewer_status="viewer: 已重启 PID=$viewer_pid 访问 http://$HOST_IP:8080/"
        else
            viewer_status="viewer: 已重启 PID=$viewer_pid 但健康检查未通过(http_code=$http_code) 访问 http://$HOST_IP:8080/"
            viewer_failed=true
        fi
    else
        viewer_status="viewer: 重启失败（未生成 PID 文件）"
        viewer_failed=true
    fi
fi

# =====================
# 3. 读取 stats.json
# =====================
scan_rate_total="N/A"
scan_rate_recent="N/A"
keygen_rate="N/A"
scanned="N/A"
hits="N/A"
total_running_sec="N/A"

if [[ -f $STATS_FILE ]]; then
    if command -v jq >/dev/null 2>&1; then
        scan_rate_total=$(jq -r '.scan_rate_total_addr_per_sec // "N/A"' "$STATS_FILE" 2>/dev/null || echo "N/A")
        scan_rate_recent=$(jq -r '.scan_rate_recent_addr_per_sec // "N/A"' "$STATS_FILE" 2>/dev/null || echo "N/A")
        keygen_rate=$(jq -r '.keygen_rate_keys_per_sec // "N/A"' "$STATS_FILE" 2>/dev/null || echo "N/A")
        scanned=$(jq -r '.scanned // "N/A"' "$STATS_FILE" 2>/dev/null || echo "N/A")
        hits=$(jq -r '.hits // "N/A"' "$STATS_FILE" 2>/dev/null || echo "N/A")
        total_running_sec=$(jq -r '.total_running_sec // "N/A"' "$STATS_FILE" 2>/dev/null || echo "N/A")
    elif command -v python3 >/dev/null 2>&1; then
        read -r scan_rate_total scan_rate_recent keygen_rate scanned hits total_running_sec <<EOF
$(python3 -c "
import json, sys
try:
    with open('$STATS_FILE') as f:
        d = json.load(f)
    print(d.get('scan_rate_total_addr_per_sec', 'N/A'))
    print(d.get('scan_rate_recent_addr_per_sec', 'N/A'))
    print(d.get('keygen_rate_keys_per_sec', 'N/A'))
    print(d.get('scanned', 'N/A'))
    print(d.get('hits', 'N/A'))
    print(d.get('total_running_sec', 'N/A'))
except Exception:
    print('N/A')
    print('N/A')
    print('N/A')
    print('N/A')
    print('N/A')
    print('N/A')
")
EOF
    fi
fi

# =====================
# 4. 失败计数
# =====================
if $scanner_failed || $viewer_failed; then
    failures=$((failures + 1))
    echo "$failures" > "$FAILURE_FILE"
else
    echo "0" > "$FAILURE_FILE"
    failures=0
fi

# =====================
# 5. 输出报告
# =====================
echo "$scanner_status"
echo "$viewer_status"
echo "扫描速度(全程)=${scan_rate_total} addr/s，扫描速度(近30)=${scan_rate_recent} addr/s，计算速度=${keygen_rate} keys/s"
echo "累计扫描=${scanned}，命中=${hits}，本次运行=${total_running_sec}s"

if [[ $failures -ge 3 ]]; then
    echo "连续失败，可能依赖或 RPC 出问题"
    if [[ -f $OUTPUT_DIR/scanner.log ]]; then
        echo "--- scanner.log 末尾 20 行 ---"
        tail -n 20 "$OUTPUT_DIR/scanner.log"
    fi
    if [[ -f $OUTPUT_DIR/viewer.log ]]; then
        echo "--- viewer.log 末尾 10 行 ---"
        tail -n 10 "$OUTPUT_DIR/viewer.log"
    fi
fi

#!/usr/bin/env bash
set -u

WORK_DIR="/workspace"
OUTPUT_DIR="${WORK_DIR}/output"
FAILURE_FILE="${OUTPUT_DIR}/keepalive_failures"
SCANNER_PID_FILE="${WORK_DIR}/.scanner.pid"
VIEWER_PID_FILE="${WORK_DIR}/.viewer.pid"
SCANNER_LOG="${OUTPUT_DIR}/scanner.log"
VIEWER_LOG="${OUTPUT_DIR}/viewer.log"
VIEWER_PORT="8080"

mkdir -p "${OUTPUT_DIR}"

is_alive() {
    local pid="$1"
    if [[ -z "${pid}" ]] || ! [[ "${pid}" =~ ^[0-9]+$ ]]; then
        return 1
    fi
    ps -p "${pid}" -o etime= >/dev/null 2>&1
}

get_etime() {
    local pid="$1"
    ps -p "${pid}" -o etime= 2>/dev/null | tr -d '[:space:]'
}

get_host() {
    local host
    host="$(hostname -I 2>/dev/null | awk '{print $1}')"
    if [[ -z "${host}" ]]; then
        host="$(hostname 2>/dev/null || echo '127.0.0.1')"
    fi
    echo "${host}"
}

read_pid() {
    local file="$1"
    if [[ -f "${file}" ]]; then
        tr -d '[:space:]' < "${file}"
    else
        echo ""
    fi
}

read_failure_count() {
    if [[ -f "${FAILURE_FILE}" ]]; then
        local count
        count="$(tr -d '[:space:]' < "${FAILURE_FILE}")"
        if [[ "${count}" =~ ^[0-9]+$ ]]; then
            echo "${count}"
        else
            echo "0"
        fi
    else
        echo "0"
    fi
}

write_failure_count() {
    echo "$1" > "${FAILURE_FILE}"
}

tail_lines() {
    local file="$1"
    local n="$2"
    if [[ -f "${file}" ]]; then
        tail -n "${n}" "${file}"
    else
        echo "(日志文件不存在: ${file})"
    fi
}

# ---------- scanner ----------
scanner_status=""
scanner_failed=0
scanner_pid=$(read_pid "${SCANNER_PID_FILE}")

if is_alive "${scanner_pid}"; then
    scanner_etime=$(get_etime "${scanner_pid}")
    scanner_status="scanner: 运行中 PID=${scanner_pid} 已运行=${scanner_etime}"
else
    cd "${WORK_DIR}" && SCAN_INTERVAL=0.3 bash run.sh >/dev/null 2>&1 &
    sleep 10
    scanner_pid=$(read_pid "${SCANNER_PID_FILE}")
    if is_alive "${scanner_pid}"; then
        scanner_status="scanner: 已重启 PID=${scanner_pid}"
    else
        scanner_status="scanner: 重启失败"
        scanner_failed=1
    fi
fi

# ---------- viewer ----------
viewer_status=""
viewer_failed=0
viewer_pid=$(read_pid "${VIEWER_PID_FILE}")

if is_alive "${viewer_pid}"; then
    viewer_etime=$(get_etime "${viewer_pid}")
    host=$(get_host)
    viewer_status="viewer: 运行中 PID=${viewer_pid} 已运行=${viewer_etime} 访问 http://${host}:${VIEWER_PORT}/"
else
    cd "${WORK_DIR}" && PORT=${VIEWER_PORT} bash start_viewer.sh >/dev/null 2>&1 &
    sleep 2
    viewer_pid=$(read_pid "${VIEWER_PID_FILE}")
    http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:${VIEWER_PORT}/" 2>/dev/null || true)
    if [[ -z "${http_code}" ]]; then
        http_code="000"
    fi
    if [[ "${http_code}" == "200" ]]; then
        viewer_status="viewer: 已重启 PID=${viewer_pid}"
    else
        viewer_status="viewer: 重启失败 (HTTP ${http_code})"
        viewer_failed=1
    fi
fi

# ---------- metrics ----------
stats_file="${OUTPUT_DIR}/stats.json"
scan_rate_total="N/A"
scan_rate_recent="N/A"
keygen_rate="N/A"
scanned="N/A"
hits="N/A"
total_running_sec="N/A"

if [[ -f "${stats_file}" ]]; then
    scan_rate_total=$(python3 -c "
import json, sys
try:
    d=json.load(open('${stats_file}'))
    print(d.get('scan_rate_total_addr_per_sec', 'N/A'))
except Exception:
    print('N/A')
" 2>/dev/null || echo "N/A")

    scan_rate_recent=$(python3 -c "
import json, sys
try:
    d=json.load(open('${stats_file}'))
    print(d.get('scan_rate_recent_addr_per_sec', 'N/A'))
except Exception:
    print('N/A')
" 2>/dev/null || echo "N/A")

    keygen_rate=$(python3 -c "
import json, sys
try:
    d=json.load(open('${stats_file}'))
    print(d.get('keygen_rate_keys_per_sec', 'N/A'))
except Exception:
    print('N/A')
" 2>/dev/null || echo "N/A")

    scanned=$(python3 -c "
import json, sys
try:
    d=json.load(open('${stats_file}'))
    print(d.get('scanned', 'N/A'))
except Exception:
    print('N/A')
" 2>/dev/null || echo "N/A")

    hits=$(python3 -c "
import json, sys
try:
    d=json.load(open('${stats_file}'))
    print(d.get('hits', 'N/A'))
except Exception:
    print('N/A')
" 2>/dev/null || echo "N/A")

    total_running_sec=$(python3 -c "
import json, sys
try:
    d=json.load(open('${stats_file}'))
    print(d.get('total_running_sec', 'N/A'))
except Exception:
    print('N/A')
" 2>/dev/null || echo "N/A")
fi

# ---------- failure counter ----------
failure_count=$(read_failure_count)
if [[ ${scanner_failed} -eq 1 || ${viewer_failed} -eq 1 ]]; then
    failure_count=$((failure_count + 1))
else
    failure_count=0
fi
write_failure_count "${failure_count}"

# ---------- report ----------
echo "=== 保活报告 $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "${scanner_status}"
echo "${viewer_status}"
echo "扫描速度(全程)=${scan_rate_total} addr/s，扫描速度(近30)=${scan_rate_recent} addr/s，计算速度=${keygen_rate} keys/s"
echo "累计扫描=${scanned}，命中=${hits}，本次运行=${total_running_sec}s"

if [[ ${failure_count} -ge 3 ]]; then
    echo ""
    echo "⚠ 连续失败，可能依赖或 RPC 出问题 (连续失败次数: ${failure_count})"
    echo "--- scanner.log 末尾 20 行 ---"
    tail_lines "${SCANNER_LOG}" 20
    echo ""
    echo "--- viewer.log 末尾 10 行 ---"
    tail_lines "${VIEWER_LOG}" 10
fi

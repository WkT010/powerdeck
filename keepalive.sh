#!/bin/bash
# 双守护保活脚本：监控 scanner.py 与 web_log_viewer.py
# 定时执行：建议 crontab -e 添加 0 * * * * /workspace/keepalive.sh

set -u

WORKDIR="/workspace"
OUTPUT_DIR="${WORKDIR}/output"
FAILURES_FILE="${OUTPUT_DIR}/keepalive_failures"
STATS_FILE="${OUTPUT_DIR}/stats.json"
SCANNER_PID_FILE="${WORKDIR}/.scanner.pid"
VIEWER_PID_FILE="${WORKDIR}/.viewer.pid"
SCANNER_LOG="${OUTPUT_DIR}/scanner.log"
VIEWER_LOG="${OUTPUT_DIR}/viewer.log"
VIEWER_PORT=8080

# 确保 output 目录存在
mkdir -p "${OUTPUT_DIR}"

# 报告变量
SCANNER_STATUS=""
VIEWER_STATUS=""
SPEED_METRICS=""
CUMULATIVE_METRICS=""
FAILURE_HINT=""
LOG_TAIL=""
SCANNER_RESTARTED=0
VIEWER_RESTARTED=0
SCANNER_FAILED=0
VIEWER_FAILED=0

# 获取主机 IP（用于 viewer 访问地址）
get_host_ip() {
    local ip=""
    # 优先尝试获取非本地回环的 IP
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [ -z "${ip}" ]; then
        ip=$(ip -4 addr show 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '^127\.' | head -n1)
    fi
    if [ -z "${ip}" ]; then
        ip="127.0.0.1"
    fi
    echo "${ip}"
}

HOST_IP=$(get_host_ip)

# 读取失败计数
read_failures() {
    if [ -f "${FAILURES_FILE}" ]; then
        cat "${FAILURES_FILE}" 2>/dev/null | tr -d '[:space:]' || echo 0
    else
        echo 0
    fi
}

# 写入失败计数
write_failures() {
    echo "$1" > "${FAILURES_FILE}"
}

FAILURE_COUNT=$(read_failures)

# 检查 scanner 进程
check_scanner() {
    if [ ! -f "${SCANNER_PID_FILE}" ]; then
        return 1
    fi
    local pid
    pid=$(cat "${SCANNER_PID_FILE}" 2>/dev/null | tr -d '[:space:]')
    if [ -z "${pid}" ]; then
        return 1
    fi
    # 验证 PID 是否为数字
    if ! [[ "${pid}" =~ ^[0-9]+$ ]]; then
        return 1
    fi
    # 检查进程是否存活
    local etime
    etime=$(ps -p "${pid}" -o etime= 2>/dev/null | tr -d '[:space:]')
    if [ -n "${etime}" ]; then
        SCANNER_STATUS="scanner: 运行中 PID=${pid} 已运行=${etime}"
        return 0
    fi
    return 1
}

# 重启 scanner
restart_scanner() {
    local start_script="${WORKDIR}/run.sh"
    if [ ! -f "${start_script}" ]; then
        SCANNER_STATUS="scanner: 启动失败 run.sh 不存在"
        SCANNER_FAILED=1
        return 1
    fi
    # 清理旧 PID 文件
    rm -f "${SCANNER_PID_FILE}"
    # 执行重启
    (cd "${WORKDIR}" && SCAN_INTERVAL=0.3 bash run.sh >/dev/null 2>&1 &)
    # 等待 10 秒让 benchmark 完成
    sleep 10
    # 检查是否启动成功
    if check_scanner; then
        local new_pid
        new_pid=$(cat "${SCANNER_PID_FILE}" 2>/dev/null | tr -d '[:space:]')
        SCANNER_STATUS="scanner: 已重启 PID=${new_pid}"
        SCANNER_RESTARTED=1
        return 0
    else
        SCANNER_STATUS="scanner: 重启失败 PID 文件未生成或进程未存活"
        SCANNER_FAILED=1
        return 1
    fi
}

# 检查 viewer 进程
check_viewer() {
    if [ ! -f "${VIEWER_PID_FILE}" ]; then
        return 1
    fi
    local pid
    pid=$(cat "${VIEWER_PID_FILE}" 2>/dev/null | tr -d '[:space:]')
    if [ -z "${pid}" ]; then
        return 1
    fi
    if ! [[ "${pid}" =~ ^[0-9]+$ ]]; then
        return 1
    fi
    local etime
    etime=$(ps -p "${pid}" -o etime= 2>/dev/null | tr -d '[:space:]')
    if [ -n "${etime}" ]; then
        VIEWER_STATUS="viewer: 运行中 PID=${pid} 已运行=${etime} 访问 http://${HOST_IP}:${VIEWER_PORT}/"
        return 0
    fi
    return 1
}

# 重启 viewer
restart_viewer() {
    local start_script="${WORKDIR}/start_viewer.sh"
    if [ ! -f "${start_script}" ]; then
        VIEWER_STATUS="viewer: 启动失败 start_viewer.sh 不存在"
        VIEWER_FAILED=1
        return 1
    fi
    rm -f "${VIEWER_PID_FILE}"
    (cd "${WORKDIR}" && PORT="${VIEWER_PORT}" bash start_viewer.sh >/dev/null 2>&1 &)
    sleep 2
    # 检查 PID 和 HTTP 响应
    if check_viewer; then
        local http_code
        http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:${VIEWER_PORT}/" 2>/dev/null || echo "000")
        if [ "${http_code}" = "200" ]; then
            local new_pid
            new_pid=$(cat "${VIEWER_PID_FILE}" 2>/dev/null | tr -d '[:space:]')
            VIEWER_STATUS="viewer: 已重启 PID=${new_pid} 访问 http://${HOST_IP}:${VIEWER_PORT}/"
            VIEWER_RESTARTED=1
            return 0
        else
            VIEWER_STATUS="viewer: 已启动但 HTTP=${http_code} PID=$(cat ${VIEWER_PID_FILE} 2>/dev/null) 访问 http://${HOST_IP}:${VIEWER_PORT}/"
            VIEWER_RESTARTED=1
            return 0
        fi
    else
        VIEWER_STATUS="viewer: 重启失败 PID 文件未生成或进程未存活"
        VIEWER_FAILED=1
        return 1
    fi
}

# 读取速度指标
read_speed_metrics() {
    if [ ! -f "${STATS_FILE}" ]; then
        SPEED_METRICS="扫描速度(全程)=N/A addr/s，扫描速度(近30)=N/A addr/s，计算速度=N/A keys/s"
        CUMULATIVE_METRICS="累计扫描=N/A，命中=N/A，本次运行=N/A s"
        return
    fi
    # 用 python 解析 JSON 更可靠（如果有 python）
    if command -v python3 >/dev/null 2>&1; then
        python3 - "${STATS_FILE}" <<'PYEOF'
import json, sys
path = sys.argv[1]
try:
    with open(path) as f:
        s = json.load(f)
    total_rate = s.get("scan_rate_total_addr_per_sec", s.get("scan_rate_total", "N/A"))
    recent_rate = s.get("scan_rate_recent_addr_per_sec", s.get("scan_rate_recent_30s", s.get("scan_rate_recent", "N/A")))
    keygen_rate = s.get("keygen_rate_keys_per_sec", s.get("keygen_rate", "N/A"))
    scanned = s.get("scanned_total", s.get("scanned", s.get("total_scanned", "N/A")))
    hits = s.get("hits_total", s.get("hits", s.get("found", "N/A")))
    running = s.get("total_running_sec", s.get("running_sec", s.get("uptime_sec", "N/A")))
    print(f"SPEED:扫描速度(全程)={total_rate} addr/s，扫描速度(近30)={recent_rate} addr/s，计算速度={keygen_rate} keys/s")
    print(f"CUM:累计扫描={scanned}，命中={hits}，本次运行={running}s")
except Exception as e:
    print(f"SPEED:扫描速度(全程)=PARSE_ERR addr/s，扫描速度(近30)=PARSE_ERR addr/s，计算速度=PARSE_ERR keys/s")
    print(f"CUM:累计扫描=PARSE_ERR，命中=PARSE_ERR，本次运行=PARSE_ERRs")
PYEOF
    else
        # 回退：用 grep/sed 简单解析
        local total recent keygen scanned hits running
        total=$(grep -o '"scan_rate_total_addr_per_sec"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9.]*' | tail -n1)
        recent=$(grep -o '"scan_rate_recent_addr_per_sec"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9.]*' | tail -n1)
        keygen=$(grep -o '"keygen_rate_keys_per_sec"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9.]*' | tail -n1)
        scanned=$(grep -oE '"(scanned_total|scanned)"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9]*' | tail -n1)
        hits=$(grep -oE '"(hits_total|hits)"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9]*' | tail -n1)
        running=$(grep -o '"total_running_sec"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9.]*' | tail -n1)
        [ -z "${total}" ] && total="N/A"
        [ -z "${recent}" ] && recent="N/A"
        [ -z "${keygen}" ] && keygen="N/A"
        [ -z "${scanned}" ] && scanned="N/A"
        [ -z "${hits}" ] && hits="N/A"
        [ -z "${running}" ] && running="N/A"
        echo "SPEED:扫描速度(全程)=${total} addr/s，扫描速度(近30)=${recent} addr/s，计算速度=${keygen} keys/s"
        echo "CUM:累计扫描=${scanned}，命中=${hits}，本次运行=${running}s"
    fi | while IFS= read -r line; do
        case "${line}" in
            SPEED:*) SPEED_METRICS="${line#SPEED:}" ;;
            CUM:*) CUMULATIVE_METRICS="${line#CUM:}" ;;
        esac
    done
    # 由于 subshell 问题，重新用文件中转
    local tmpfile
    tmpfile=$(mktemp)
    if command -v python3 >/dev/null 2>&1; then
        python3 - "${STATS_FILE}" > "${tmpfile}" <<'PYEOF'
import json, sys
path = sys.argv[1]
try:
    with open(path) as f:
        s = json.load(f)
    total_rate = s.get("scan_rate_total_addr_per_sec", s.get("scan_rate_total", "N/A"))
    recent_rate = s.get("scan_rate_recent_addr_per_sec", s.get("scan_rate_recent_30s", s.get("scan_rate_recent", "N/A")))
    keygen_rate = s.get("keygen_rate_keys_per_sec", s.get("keygen_rate", "N/A"))
    scanned = s.get("scanned_total", s.get("scanned", s.get("total_scanned", "N/A")))
    hits = s.get("hits_total", s.get("hits", s.get("found", "N/A")))
    running = s.get("total_running_sec", s.get("running_sec", s.get("uptime_sec", "N/A")))
    print(f"扫描速度(全程)={total_rate} addr/s，扫描速度(近30)={recent_rate} addr/s，计算速度={keygen_rate} keys/s")
    print(f"累计扫描={scanned}，命中={hits}，本次运行={running}s")
except Exception as e:
    print(f"扫描速度(全程)=PARSE_ERR addr/s，扫描速度(近30)=PARSE_ERR addr/s，计算速度=PARSE_ERR keys/s")
    print(f"累计扫描=PARSE_ERR，命中=PARSE_ERR，本次运行=PARSE_ERRs")
PYEOF
    else
        local total recent keygen scanned hits running
        total=$(grep -o '"scan_rate_total_addr_per_sec"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9.]*' | tail -n1)
        recent=$(grep -o '"scan_rate_recent_addr_per_sec"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9.]*' | tail -n1)
        keygen=$(grep -o '"keygen_rate_keys_per_sec"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9.]*' | tail -n1)
        scanned=$(grep -oE '"(scanned_total|scanned)"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9]*' | tail -n1)
        hits=$(grep -oE '"(hits_total|hits)"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9]*' | tail -n1)
        running=$(grep -o '"total_running_sec"[^,}]*' "${STATS_FILE}" 2>/dev/null | grep -o '[0-9.]*' | tail -n1)
        [ -z "${total}" ] && total="N/A"
        [ -z "${recent}" ] && recent="N/A"
        [ -z "${keygen}" ] && keygen="N/A"
        [ -z "${scanned}" ] && scanned="N/A"
        [ -z "${hits}" ] && hits="N/A"
        [ -z "${running}" ] && running="N/A"
        echo "扫描速度(全程)=${total} addr/s，扫描速度(近30)=${recent} addr/s，计算速度=${keygen} keys/s" > "${tmpfile}"
        echo "累计扫描=${scanned}，命中=${hits}，本次运行=${running}s" >> "${tmpfile}"
    fi
    SPEED_METRICS=$(sed -n '1p' "${tmpfile}")
    CUMULATIVE_METRICS=$(sed -n '2p' "${tmpfile}")
    rm -f "${tmpfile}"
}

# 收集日志末尾
collect_log_tails() {
    local part=""
    if [ -f "${SCANNER_LOG}" ]; then
        part="${part}===== scanner.log 末尾 20 行 =====
$(tail -n 20 "${SCANNER_LOG}" 2>/dev/null)
"
    else
        part="${part}===== scanner.log 不存在 =====
"
    fi
    if [ -f "${VIEWER_LOG}" ]; then
        part="${part}
===== viewer.log 末尾 10 行 =====
$(tail -n 10 "${VIEWER_LOG}" 2>/dev/null)
"
    else
        part="${part}
===== viewer.log 不存在 =====
"
    fi
    LOG_TAIL="${part}"
}

# ========== 主流程 ==========

# 1. 检查并重启 scanner
if check_scanner; then
    :
else
    restart_scanner
fi

# 2. 检查并重启 viewer
if check_viewer; then
    :
else
    restart_viewer
fi

# 3. 更新失败计数
if [ "${SCANNER_FAILED}" -eq 1 ] || [ "${VIEWER_FAILED}" -eq 1 ]; then
    FAILURE_COUNT=$((FAILURE_COUNT + 1))
    write_failures "${FAILURE_COUNT}"
else
    FAILURE_COUNT=0
    write_failures "0"
fi

# 4. 读取速度指标
read_speed_metrics

# 5. 组装输出
echo "============================================="
echo "  双守护保活报告 $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================="
echo "${SCANNER_STATUS}"
echo "${VIEWER_STATUS}"
echo "---------------------------------------------"
echo "${SPEED_METRICS}"
echo "${CUMULATIVE_METRICS}"
echo "---------------------------------------------"
echo "连续失败计数=${FAILURE_COUNT}"

# 6. 连续失败 >=3 时报告警告并附带日志
if [ "${FAILURE_COUNT}" -ge 3 ]; then
    FAILURE_HINT="⚠️  连续失败(>=3)，可能依赖或 RPC 出问题"
    collect_log_tails
    echo ""
    echo "${FAILURE_HINT}"
    echo "---------------------------------------------"
    echo "${LOG_TAIL}"
fi

echo "============================================="

exit 0

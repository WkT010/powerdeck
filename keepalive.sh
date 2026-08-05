#!/bin/bash
# 双守护保活脚本：监控 scanner.py 与 web_log_viewer.py
# 每小时执行：每小时检查、未运行则重启、报告速度指标 + viewer 访问地址

set -u

WORKSPACE="/workspace"
OUTPUT_DIR="${WORKSPACE}/output"
SCANNER_PID_FILE="${WORKSPACE}/.scanner.pid"
VIEWER_PID_FILE="${WORKSPACE}/.viewer.pid"
FAILURES_FILE="${OUTPUT_DIR}/keepalive_failures"
STATS_FILE="${OUTPUT_DIR}/stats.json"
SCANNER_LOG="${OUTPUT_DIR}/scanner.log"
VIEWER_LOG="${OUTPUT_DIR}/viewer.log"

mkdir -p "${OUTPUT_DIR}"

# 初始化失败计数文件
if [ ! -f "${FAILURES_FILE}" ]; then
    echo "0" > "${FAILURES_FILE}"
fi

SCANNER_STATUS=""
VIEWER_STATUS=""
SCANNER_ACTION="none"   # none | restarted | ok
VIEWER_ACTION="none"
SCANNER_PID=""
VIEWER_PID=""
SCANNER_ETIME=""
VIEWER_ETIME=""

# ========== 1. 检查 scanner ==========
check_scanner() {
    local pid=""
    if [ -f "${SCANNER_PID_FILE}" ]; then
        pid=$(cat "${SCANNER_PID_FILE}" 2>/dev/null | tr -d '[:space:]')
    fi

    if [ -n "${pid}" ]; then
        local etime
        etime=$(ps -p "${pid}" -o etime= 2>/dev/null | tr -d '[:space:]')
        if [ -n "${etime}" ]; then
            # 进程存活
            SCANNER_PID="${pid}"
            SCANNER_ETIME="${etime}"
            SCANNER_ACTION="ok"
            SCANNER_STATUS="scanner: 运行中 PID=${pid} 已运行=${etime}"
            return 0
        fi
    fi

    # 未运行 -> 重启
    echo "[keepalive] scanner 未运行，正在重启..."
    (cd "${WORKSPACE}" && SCAN_INTERVAL=0.3 bash run.sh >/dev/null 2>&1 &)
    local start_wait=10
    sleep "${start_wait}"

    # 读取新 PID
    local new_pid=""
    if [ -f "${SCANNER_PID_FILE}" ]; then
        new_pid=$(cat "${SCANNER_PID_FILE}" 2>/dev/null | tr -d '[:space:]')
    fi

    if [ -n "${new_pid}" ] && ps -p "${new_pid}" -o etime= >/dev/null 2>&1; then
        SCANNER_PID="${new_pid}"
        SCANNER_ACTION="restarted"
        SCANNER_STATUS="scanner: 已重启 PID=${new_pid}"
        return 0
    else
        SCANNER_ACTION="failed"
        SCANNER_STATUS="scanner: 重启失败"
        return 1
    fi
}

# ========== 2. 检查 viewer ==========
check_viewer() {
    local pid=""
    if [ -f "${VIEWER_PID_FILE}" ]; then
        pid=$(cat "${VIEWER_PID_FILE}" 2>/dev/null | tr -d '[:space:]')
    fi

    local viewer_host
    viewer_host=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -z "${viewer_host}" ] && viewer_host="127.0.0.1"

    if [ -n "${pid}" ]; then
        local etime
        etime=$(ps -p "${pid}" -o etime= 2>/dev/null | tr -d '[:space:]')
        if [ -n "${etime}" ]; then
            # 进程存活
            VIEWER_PID="${pid}"
            VIEWER_ETIME="${etime}"
            VIEWER_ACTION="ok"
            VIEWER_STATUS="viewer: 运行中 PID=${pid} 已运行=${etime} 访问 http://${viewer_host}:8080/"
            return 0
        fi
    fi

    # 未运行 -> 重启
    echo "[keepalive] viewer 未运行，正在重启..."
    (cd "${WORKSPACE}" && PORT=8080 bash start_viewer.sh >/dev/null 2>&1 &)
    sleep 2

    # 读取新 PID
    local new_pid=""
    if [ -f "${VIEWER_PID_FILE}" ]; then
        new_pid=$(cat "${VIEWER_PID_FILE}" 2>/dev/null | tr -d '[:space:]')
    fi

    # curl 健康检查
    local http_code
    http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null)
    [ -z "${http_code}" ] && http_code="000"

    if [ -n "${new_pid}" ] && ps -p "${new_pid}" -o etime= >/dev/null 2>&1 && [ "${http_code}" = "200" ]; then
        VIEWER_PID="${new_pid}"
        VIEWER_ACTION="restarted"
        VIEWER_STATUS="viewer: 已重启 PID=${new_pid}"
        return 0
    else
        VIEWER_ACTION="failed"
        VIEWER_STATUS="viewer: 重启失败 (HTTP=${http_code})"
        return 1
    fi
}

# ========== 3. 读取 stats.json 速度指标 ==========
read_stats() {
    # 默认值
    local scan_rate_total="N/A"
    local scan_rate_recent="N/A"
    local keygen_rate="N/A"
    local scanned="N/A"
    local hits="N/A"
    local total_running="N/A"

    if [ -f "${STATS_FILE}" ]; then
        # 使用 python3 解析 JSON，避免依赖 jq
        if command -v python3 >/dev/null 2>&1; then
            read -r scan_rate_total scan_rate_recent keygen_rate scanned hits total_running <<< "$(
                python3 -c "
import json, sys
try:
    with open('${STATS_FILE}', 'r') as f:
        s = json.load(f)
    def g(k, alt='N/A'):
        v = s.get(k)
        if v is None:
            return alt
        if isinstance(v, float):
            return f'{v:.2f}'
        return str(v)
    print(g('scan_rate_total_addr_per_sec'), g('scan_rate_recent_addr_per_sec'),
          g('keygen_rate_keys_per_sec'), g('scanned'), g('hits'), g('total_running_sec'))
except Exception as e:
    print('N/A N/A N/A N/A N/A N/A')
"
            )"
        elif command -v jq >/dev/null 2>&1; then
            scan_rate_total=$(jq -r '.scan_rate_total_addr_per_sec // "N/A"' "${STATS_FILE}" 2>/dev/null)
            scan_rate_recent=$(jq -r '.scan_rate_recent_addr_per_sec // "N/A"' "${STATS_FILE}" 2>/dev/null)
            keygen_rate=$(jq -r '.keygen_rate_keys_per_sec // "N/A"' "${STATS_FILE}" 2>/dev/null)
            scanned=$(jq -r '.scanned // "N/A"' "${STATS_FILE}" 2>/dev/null)
            hits=$(jq -r '.hits // "N/A"' "${STATS_FILE}" 2>/dev/null)
            total_running=$(jq -r '.total_running_sec // "N/A"' "${STATS_FILE}" 2>/dev/null)
        fi
    fi

    # 为 N/A 的值去掉单位，避免显示成 "N/As" / "N/A addr/s"
    local fmt_total fmt_recent fmt_key fmt_run
    [ "${scan_rate_total}" = "N/A" ] && fmt_total="N/A" || fmt_total="${scan_rate_total} addr/s"
    [ "${scan_rate_recent}" = "N/A" ] && fmt_recent="N/A" || fmt_recent="${scan_rate_recent} addr/s"
    [ "${keygen_rate}" = "N/A" ] && fmt_key="N/A" || fmt_key="${keygen_rate} keys/s"
    [ "${total_running}" = "N/A" ] && fmt_run="N/A" || fmt_run="${total_running}s"
    SPEED_LINE_1="扫描速度(全程)=${fmt_total}，扫描速度(近30)=${fmt_recent}，计算速度=${fmt_key}"
    SPEED_LINE_2="累计扫描=${scanned}，命中=${hits}，本次运行=${fmt_run}"
}

# ========== 4. 连续失败计数 ==========
update_failures() {
    local any_failed=0
    [ "${SCANNER_ACTION}" = "failed" ] && any_failed=1
    [ "${VIEWER_ACTION}" = "failed" ] && any_failed=1

    local current
    current=$(cat "${FAILURES_FILE}" 2>/dev/null || echo "0")
    current=${current:-0}

    if [ "${any_failed}" -eq 1 ]; then
        current=$((current + 1))
    else
        current=0
    fi
    echo "${current}" > "${FAILURES_FILE}"

    if [ "${current}" -ge 3 ]; then
        FAILURE_ALERT="连续失败，可能依赖或 RPC 出问题 (连续${current}次)"
    else
        FAILURE_ALERT=""
    fi
}

# ========== 日志末尾截取 ==========
tail_logs() {
    SCANNER_LOG_TAIL=""
    VIEWER_LOG_TAIL=""
    if [ -f "${SCANNER_LOG}" ]; then
        SCANNER_LOG_TAIL=$(tail -n 20 "${SCANNER_LOG}" 2>/dev/null || echo "")
    fi
    if [ -f "${VIEWER_LOG}" ]; then
        VIEWER_LOG_TAIL=$(tail -n 10 "${VIEWER_LOG}" 2>/dev/null || echo "")
    fi
}

# ========== 主流程 ==========
echo "============================================"
echo " 双守护保活检查 - $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

scanner_rc=0
viewer_rc=0
check_scanner || scanner_rc=1
check_viewer   || viewer_rc=1

read_stats
update_failures
tail_logs

# ========== 输出报告 ==========
echo ""
echo "---------------- 状态报告 ----------------"
echo "${SCANNER_STATUS}"
echo "${VIEWER_STATUS}"
echo ""
echo "${SPEED_LINE_1}"
echo "${SPEED_LINE_2}"

if [ -n "${FAILURE_ALERT}" ]; then
    echo ""
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "⚠️  ${FAILURE_ALERT}"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    if [ -n "${SCANNER_LOG_TAIL}" ]; then
        echo ""
        echo "----- scanner.log 末尾 20 行 -----"
        echo "${SCANNER_LOG_TAIL}"
    fi
    if [ -n "${VIEWER_LOG_TAIL}" ]; then
        echo ""
        echo "----- viewer.log 末尾 10 行 -----"
        echo "${VIEWER_LOG_TAIL}"
    fi
fi

echo ""
echo "-------------------------------------------"
echo "保活检查完成。"

# 若有失败则以非 0 退出，便于调度器感知
if [ "${scanner_rc}" -ne 0 ] || [ "${viewer_rc}" -ne 0 ]; then
    exit 1
fi
exit 0

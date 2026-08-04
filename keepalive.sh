#!/usr/bin/env bash
# ============================================================
# keepalive.sh — 双守护保活脚本
# 每小时由 cron 或手动执行，检查 scanner / viewer 是否存活，
# 未存活则重启，并输出结构化状态报告。
# ============================================================

set -euo pipefail

WORKSPACE="/workspace"
OUTPUT_DIR="${WORKSPACE}/output"
SCANNER_PID_FILE="${WORKSPACE}/.scanner.pid"
VIEWER_PID_FILE="${WORKSPACE}/.viewer.pid"
FAILURE_FILE="${OUTPUT_DIR}/keepalive_failures"
SCANNER_LOG="${OUTPUT_DIR}/scanner.log"
VIEWER_LOG="${OUTPUT_DIR}/viewer.log"
STATS_FILE="${OUTPUT_DIR}/stats.json"
VIEWER_PORT=8080

# 确保输出目录存在
mkdir -p "${OUTPUT_DIR}"
touch "${FAILURE_FILE}" 2>/dev/null || true

# ----------------------------------------------------------
# 工具函数
# ----------------------------------------------------------

# 读取 PID 文件，返回 PID（文件不存在或为空则返回空）
read_pid() {
    local pid_file="$1"
    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null | tr -d '[:space:]')
        if [[ -n "$pid" && "$pid" =~ ^[0-9]+$ ]]; then
            echo "$pid"
            return
        fi
    fi
    echo ""
}

# 检查进程是否存活，存活则输出 etime，否则输出空
check_alive() {
    local pid="$1"
    if [[ -n "$pid" ]]; then
        local etime
        etime=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d '[:space:]') || true
        if [[ -n "$etime" ]]; then
            echo "$etime"
            return 0
        fi
    fi
    return 1
}

# ----------------------------------------------------------
# 1. 检查 scanner
# ----------------------------------------------------------

scanner_status=""
scanner_pid=""
scanner_etime=""
scanner_restarted=false

scanner_pid=$(read_pid "$SCANNER_PID_FILE")

if check_alive "$scanner_pid" >/dev/null 2>&1; then
    scanner_etime=$(ps -p "$scanner_pid" -o etime= 2>/dev/null | tr -d '[:space:]')
    scanner_status="运行中"
else
    # scanner 不存活，重启
    (cd "$WORKSPACE" && SCAN_INTERVAL=0.3 bash run.sh) &
    # 等待 benchmark 完成
    sleep 10
    scanner_pid=$(read_pid "$SCANNER_PID_FILE")
    if [[ -n "$scanner_pid" ]] && check_alive "$scanner_pid" >/dev/null 2>&1; then
        scanner_etime=$(ps -p "$scanner_pid" -o etime= 2>/dev/null | tr -d '[:space:]')
        scanner_status="已重启"
        scanner_restarted=true
    else
        scanner_status="重启失败"
        scanner_pid="N/A"
    fi
fi

# ----------------------------------------------------------
# 2. 检查 viewer
# ----------------------------------------------------------

viewer_status=""
viewer_pid=""
viewer_etime=""
viewer_restarted=false

viewer_pid=$(read_pid "$VIEWER_PID_FILE")

if check_alive "$viewer_pid" >/dev/null 2>&1; then
    viewer_etime=$(ps -p "$viewer_pid" -o etime= 2>/dev/null | tr -d '[:space:]')
    viewer_status="运行中"
else
    # viewer 不存活，重启
    (cd "$WORKSPACE" && PORT=8080 bash start_viewer.sh) &
    sleep 2
    viewer_pid=$(read_pid "$VIEWER_PID_FILE")
    if [[ -n "$viewer_pid" ]] && check_alive "$viewer_pid" >/dev/null 2>&1; then
        viewer_etime=$(ps -p "$viewer_pid" -o etime= 2>/dev/null | tr -d '[:space:]')
        viewer_status="已重启"
        viewer_restarted=true
    else
        viewer_status="重启失败"
        viewer_pid="N/A"
    fi
fi

# 2.4 确认 viewer HTTP 可达
viewer_http_ok=false
if [[ "$viewer_status" == "运行中" || "$viewer_restarted" == true ]]; then
    http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:${VIEWER_PORT}/" 2>/dev/null) || http_code="000"
    if [[ "$http_code" == "200" ]]; then
        viewer_http_ok=true
    fi
fi

# ----------------------------------------------------------
# 3. 读取速度指标
# ----------------------------------------------------------

scan_rate_total=""
scan_rate_recent=""
keygen_rate=""
scanned=""
hits=""
total_running_sec=""

if [[ -f "$STATS_FILE" ]]; then
    # 用 python3 解析 JSON（兼容性好），若无 python3 则用 grep
    if command -v python3 &>/dev/null; then
        eval "$(python3 -c "
import json, sys
try:
    with open('${STATS_FILE}') as f:
        d = json.load(f)
    print('scan_rate_total=' + repr(d.get('scan_rate_total_addr_per_sec', 'N/A')))
    print('scan_rate_recent=' + repr(d.get('scan_rate_recent_addr_per_sec', 'N/A')))
    print('keygen_rate=' + repr(d.get('keygen_rate_keys_per_sec', 'N/A')))
    print('scanned=' + repr(d.get('scanned', 'N/A')))
    print('hits=' + repr(d.get('hits', 'N/A')))
    print('total_running_sec=' + repr(d.get('total_running_sec', 'N/A')))
except Exception as e:
    print('scan_rate_total=\"N/A\"')
    print('scan_rate_recent=\"N/A\"')
    print('keygen_rate=\"N/A\"')
    print('scanned=\"N/A\"')
    print('hits=\"N/A\"')
    print('total_running_sec=\"N/A\"')
" 2>/dev/null)" || {
            scan_rate_total="N/A"
            scan_rate_recent="N/A"
            keygen_rate="N/A"
            scanned="N/A"
            hits="N/A"
            total_running_sec="N/A"
        }
    else
        scan_rate_total="N/A"
        scan_rate_recent="N/A"
        keygen_rate="N/A"
        scanned="N/A"
        hits="N/A"
        total_running_sec="N/A"
    fi
else
    scan_rate_total="N/A"
    scan_rate_recent="N/A"
    keygen_rate="N/A"
    scanned="N/A"
    hits="N/A"
    total_running_sec="N/A"
fi

# ----------------------------------------------------------
# 4. 连续失败计数
# ----------------------------------------------------------

current_failures=$(cat "${FAILURE_FILE}" 2>/dev/null | tr -d '[:space:]')
[[ -z "$current_failures" ]] && current_failures=0

any_failure=false
[[ "$scanner_status" == "重启失败" ]] && any_failure=true
[[ "$viewer_status" == "重启失败" ]] && any_failure=true
[[ "$viewer_http_ok" == false && "$viewer_status" != "运行中" ]] && any_failure=true

if $any_failure; then
    current_failures=$((current_failures + 1))
else
    current_failures=0
fi
echo "$current_failures" > "${FAILURE_FILE}"

# ----------------------------------------------------------
# 5. 输出结构化报告
# ----------------------------------------------------------

# 获取主机地址
hostname_str=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
[[ -z "$hostname_str" ]] && hostname_str="127.0.0.1"

echo "======== 保活报告 $(date '+%Y-%m-%d %H:%M:%S') ========"

if [[ "$scanner_status" == "运行中" ]]; then
    echo "scanner: 运行中 PID=${scanner_pid} 已运行=${scanner_etime}"
elif [[ "$scanner_status" == "已重启" ]]; then
    echo "scanner: 已重启 PID=${scanner_pid}"
else
    echo "scanner: ${scanner_status}"
fi

if [[ "$viewer_status" == "运行中" ]]; then
    echo "viewer: 运行中 PID=${viewer_pid} 已运行=${viewer_etime} 访问 http://${hostname_str}:${VIEWER_PORT}/"
elif [[ "$viewer_status" == "已重启" ]]; then
    echo "viewer: 已重启 PID=${viewer_pid} 访问 http://${hostname_str}:${VIEWER_PORT}/"
else
    echo "viewer: ${viewer_status}"
fi

echo "扫描速度(全程)=${scan_rate_total} addr/s，扫描速度(近30)=${scan_rate_recent} addr/s，计算速度=${keygen_rate} keys/s"
echo "累计扫描=${scanned}，命中=${hits}，本次运行=${total_running_sec}s"

# 连续失败 >=3 时附加诊断
if [[ "$current_failures" -ge 3 ]]; then
    echo ""
    echo "⚠ 连续失败 ${current_failures} 次，可能依赖或 RPC 出问题"
    echo "--- scanner.log 末尾 20 行 ---"
    if [[ -f "$SCANNER_LOG" ]]; then
        tail -20 "$SCANNER_LOG" 2>/dev/null || echo "(无法读取)"
    else
        echo "(文件不存在)"
    fi
    echo "--- viewer.log 末尾 10 行 ---"
    if [[ -f "$VIEWER_LOG" ]]; then
        tail -10 "$VIEWER_LOG" 2>/dev/null || echo "(无法读取)"
    else
        echo "(文件不存在)"
    fi
fi

echo "============================================================"

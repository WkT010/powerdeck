#!/bin/bash
set -u

# ============================================================
# 双守护保活脚本：scanner.py + web_log_viewer.py
# 功能：存活检查 → 按需重启 → 采集速度指标 → 结构化报告
# ============================================================

WORKDIR="/workspace"
OUTPUT_DIR="$WORKDIR/output"
STATS_FILE="$OUTPUT_DIR/stats.json"
FAIL_COUNT_FILE="$OUTPUT_DIR/keepalive_failures"
SCANNER_PID_FILE="$WORKDIR/.scanner.pid"
VIEWER_PID_FILE="$WORKDIR/.viewer.pid"
VIEWER_PORT=8080

# ---------- 工具函数 ----------

# 读取 JSON 字段（使用 python3 -c 保证兼容性）
read_json_field() {
    local field="$1"
    python3 -c "
import json, sys
try:
    with open('$STATS_FILE', 'r') as f:
        data = json.load(f)
    val = data.get('$field', 0)
    # 格式化输出：数字保留 2 位小数，整数原样
    if isinstance(val, float):
        print(f'{val:.2f}')
    else:
        print(val)
except Exception:
    print(0)
" 2>/dev/null
}

# 获取主机访问地址（优先取 hostname -I 的第一个非内网 IP，其次 localhost）
get_host_addr() {
    local ip
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [ -z "$ip" ]; then
        ip="127.0.0.1"
    fi
    echo "$ip"
}

# 读取失败计数
read_fail_count() {
    if [ -f "$FAIL_COUNT_FILE" ]; then
        local n
        n=$(cat "$FAIL_COUNT_FILE" 2>/dev/null | tr -cd '0-9')
        [ -z "$n" ] && n=0
        echo "$n"
    else
        echo 0
    fi
}

# 写入失败计数
write_fail_count() {
    echo "$1" > "$FAIL_COUNT_FILE"
}

# ---------- 1. Scanner 检查与重启 ----------

check_scanner() {
    # 返回值： 0=正常运行，输出 "PID=<pid> ETIME=<etime>"
    #          1=需要重启，重启后输出 "RESTARTED PID=<pid>"
    #          2=重启失败
    local pid=""
    local etime=""

    # 1.1 读 PID 文件
    if [ -f "$SCANNER_PID_FILE" ]; then
        pid=$(cat "$SCANNER_PID_FILE" 2>/dev/null | tr -cd '0-9')
    fi

    # 1.2 用 ps 判断存活
    if [ -n "$pid" ]; then
        etime=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ')
        if [ -n "$etime" ]; then
            echo "ALIVE PID=$pid ETIME=$etime"
            return 0
        fi
    fi

    # 1.3 不存活，执行重启
    echo "[keepalive] Scanner 不存活 (PID=${pid:-N/A})，正在重启..." >&2
    (cd "$WORKDIR" && SCAN_INTERVAL=0.3 bash run.sh) >/dev/null 2>&1
    local rc=$?
    sleep 10  # 等 benchmark 完成

    # 验证重启结果
    local new_pid=""
    local new_etime=""
    if [ -f "$SCANNER_PID_FILE" ]; then
        new_pid=$(cat "$SCANNER_PID_FILE" 2>/dev/null | tr -cd '0-9')
    fi
    if [ -n "$new_pid" ]; then
        new_etime=$(ps -p "$new_pid" -o etime= 2>/dev/null | tr -d ' ')
        if [ -n "$new_etime" ]; then
            echo "RESTARTED PID=$new_pid"
            return 0
        fi
    fi

    echo "FAILED"
    return 2
}

# ---------- 2. Viewer 检查与重启 ----------

check_viewer() {
    local pid=""
    local etime=""

    # 2.1 读 PID 文件
    if [ -f "$VIEWER_PID_FILE" ]; then
        pid=$(cat "$VIEWER_PID_FILE" 2>/dev/null | tr -cd '0-9')
    fi

    # 2.2 用 ps 判断存活
    if [ -n "$pid" ]; then
        etime=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ')
        if [ -n "$etime" ]; then
            # 2.4 用 curl 确认 HTTP 200
            local http_code
            http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$VIEWER_PORT/" 2>/dev/null)
            if [ "$http_code" = "200" ]; then
                echo "ALIVE PID=$pid ETIME=$etime"
                return 0
            else
                echo "[keepalive] Viewer 进程存活但 HTTP 非 200 (code=$http_code)，准备重启..." >&2
            fi
        fi
    fi

    # 2.3 不存活或 HTTP 异常，执行重启
    echo "[keepalive] Viewer 不存活 (PID=${pid:-N/A})，正在重启..." >&2
    (cd "$WORKDIR" && PORT=$VIEWER_PORT bash start_viewer.sh) >/dev/null 2>&1
    local rc=$?
    sleep 2

    # 验证重启结果（PID + HTTP 200）
    local new_pid=""
    local new_etime=""
    local tries=0
    while [ $tries -lt 5 ]; do
        if [ -f "$VIEWER_PID_FILE" ]; then
            new_pid=$(cat "$VIEWER_PID_FILE" 2>/dev/null | tr -cd '0-9')
        fi
        if [ -n "$new_pid" ]; then
            new_etime=$(ps -p "$new_pid" -o etime= 2>/dev/null | tr -d ' ')
            if [ -n "$new_etime" ]; then
                local http_code
                http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$VIEWER_PORT/" 2>/dev/null)
                if [ "$http_code" = "200" ]; then
                    echo "RESTARTED PID=$new_pid"
                    return 0
                fi
            fi
        fi
        sleep 1
        tries=$((tries + 1))
    done

    echo "FAILED"
    return 2
}

# ---------- 5. 失败日志输出 ----------

dump_failure_logs() {
    echo ""
    echo "========== 失败诊断信息 =========="
    echo "--- scanner.log 末尾 20 行 ---"
    if [ -f "$OUTPUT_DIR/scanner.log" ]; then
        tail -n 20 "$OUTPUT_DIR/scanner.log" || echo "(无法读取 scanner.log)"
    else
        echo "(scanner.log 不存在)"
    fi
    echo ""
    echo "--- viewer.log 末尾 10 行 ---"
    if [ -f "$OUTPUT_DIR/viewer.log" ]; then
        tail -n 10 "$OUTPUT_DIR/viewer.log" || echo "(无法读取 viewer.log)"
    else
        echo "(viewer.log 不存在)"
    fi
}

# ---------- 主流程 ----------

main() {
    echo "============================================="
    echo " 双守护保活检查 @ $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================="
    echo ""

    # 运行检查
    local scanner_result viewer_result
    scanner_result=$(check_scanner)
    scanner_rc=$?
    viewer_result=$(check_viewer)
    viewer_rc=$?

    # 解析 scanner 状态
    local scanner_status=""
    local scanner_pid=""
    local scanner_etime=""
    if echo "$scanner_result" | grep -q "^ALIVE"; then
        scanner_pid=$(echo "$scanner_result" | sed -n 's/.*PID=\([0-9]*\).*/\1/p')
        scanner_etime=$(echo "$scanner_result" | sed -n 's/.*ETIME=\([^ ]*\).*/\1/p')
        scanner_status="scanner: 运行中 PID=${scanner_pid} 已运行=${scanner_etime}"
    elif echo "$scanner_result" | grep -q "^RESTARTED"; then
        scanner_pid=$(echo "$scanner_result" | sed -n 's/.*PID=\([0-9]*\).*/\1/p')
        scanner_status="scanner: 已重启 PID=${scanner_pid}"
    else
        scanner_status="scanner: 启动失败"
    fi

    # 解析 viewer 状态
    local viewer_status=""
    local viewer_pid=""
    local viewer_etime=""
    local host_addr
    host_addr=$(get_host_addr)
    if echo "$viewer_result" | grep -q "^ALIVE"; then
        viewer_pid=$(echo "$viewer_result" | sed -n 's/.*PID=\([0-9]*\).*/\1/p')
        viewer_etime=$(echo "$viewer_result" | sed -n 's/.*ETIME=\([^ ]*\).*/\1/p')
        viewer_status="viewer: 运行中 PID=${viewer_pid} 已运行=${viewer_etime} 访问 http://${host_addr}:${VIEWER_PORT}/"
    elif echo "$viewer_result" | grep -q "^RESTARTED"; then
        viewer_pid=$(echo "$viewer_result" | sed -n 's/.*PID=\([0-9]*\).*/\1/p')
        viewer_status="viewer: 已重启 PID=${viewer_pid} 访问 http://${host_addr}:${VIEWER_PORT}/"
    else
        viewer_status="viewer: 启动失败（或端口 ${VIEWER_PORT} 未返回 HTTP 200）"
    fi

    # 失败计数更新
    local fail_count
    fail_count=$(read_fail_count)
    if [ $scanner_rc -eq 2 ] || [ $viewer_rc -eq 2 ]; then
        # 任一服务拉起失败则 +1
        fail_count=$((fail_count + 1))
        write_fail_count "$fail_count"
    elif [ $scanner_rc -eq 0 ] && [ $viewer_rc -eq 0 ]; then
        # 都成功则清 0
        fail_count=0
        write_fail_count 0
    fi

    # ---------- 4. 输出结构化报告 ----------
    echo "======= 保活报告 ======="
    echo "$scanner_status"
    echo "$viewer_status"

    # 读取速度指标
    local scan_total scan_recent keygen_rate scanned hits running_sec
    scan_total=$(read_json_field "scan_rate_total_addr_per_sec")
    scan_recent=$(read_json_field "scan_rate_recent_addr_per_sec")
    keygen_rate=$(read_json_field "keygen_rate_keys_per_sec")
    scanned=$(read_json_field "scanned")
    hits=$(read_json_field "hits")
    running_sec=$(read_json_field "total_running_sec")

    echo "扫描速度(全程)=${scan_total} addr/s，扫描速度(近30)=${scan_recent} addr/s，计算速度=${keygen_rate} keys/s"
    echo "累计扫描=${scanned}，命中=${hits}，本次运行=${running_sec}s"
    echo "连续失败计数=${fail_count}"

    # 连续失败 >=3 时报告
    if [ "$fail_count" -ge 3 ]; then
        echo ""
        echo "⚠️  连续失败，可能依赖或 RPC 出问题"
        dump_failure_logs
    fi

    echo "===== 报告结束 ====="
}

main "$@"

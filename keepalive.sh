#!/bin/bash
# 双守护保活任务：每小时检查 scanner.py 与 web_log_viewer.py 是否在持续运行

set -e

WORKSPACE="/workspace"
OUTPUT_DIR="$WORKSPACE/output"
SCANNER_PID_FILE="$WORKSPACE/.scanner.pid"
VIEWER_PID_FILE="$WORKSPACE/.viewer.pid"
FAILURES_FILE="$OUTPUT_DIR/keepalive_failures"
STATS_FILE="$OUTPUT_DIR/stats.json"
SCANNER_LOG="$OUTPUT_DIR/scanner.log"
VIEWER_LOG="$OUTPUT_DIR/viewer.log"

# 确保输出目录存在
mkdir -p "$OUTPUT_DIR"

# 初始化失败计数文件
if [ ! -f "$FAILURES_FILE" ]; then
    echo 0 > "$FAILURES_FILE"
fi

# 获取本机 IP 地址（优先外网 IP，否则用 127.0.0.1）
get_host_ip() {
    local ip=$(curl -s -m 2 ifconfig.me 2>/dev/null || echo "")
    if [ -z "$ip" ]; then
        ip="127.0.0.1"
    fi
    echo "$ip"
}

# 检查进程是否存活
check_process_alive() {
    local pid=$1
    if [ -z "$pid" ] || [ "$pid" == "0" ]; then
        return 1
    fi

    if ps -p "$pid" -o etime= >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# 获取进程已运行时间
get_process_etime() {
    local pid=$1
    ps -p "$pid" -o etime= 2>/dev/null | tr -d ' '
}

# 重启 scanner
restart_scanner() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 重启 scanner..."
    cd "$WORKSPACE"
    SCAN_INTERVAL=0.3 bash run.sh >/dev/null 2>&1 &

    # 等待 10 秒让 benchmark 完成
    sleep 10

    # 读取新 PID
    if [ -f "$SCANNER_PID_FILE" ]; then
        local new_pid=$(cat "$SCANNER_PID_FILE")
        echo "$new_pid"
    else
        echo ""
    fi
}

# 重启 viewer
restart_viewer() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 重启 viewer..."
    cd "$WORKSPACE"
    PORT=8080 bash start_viewer.sh >/dev/null 2>&1 &

    # 等待 2 秒
    sleep 2

    # 读取新 PID
    if [ -f "$VIEWER_PID_FILE" ]; then
        local new_pid=$(cat "$VIEWER_PID_FILE")
        echo "$new_pid"
    else
        echo ""
    fi
}

# 检查 viewer HTTP 服务是否正常
check_viewer_http() {
    local http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null)
    if [ "$http_code" == "200" ]; then
        return 0
    else
        return 1
    fi
}

# 读取速度指标
read_stats() {
    if [ -f "$STATS_FILE" ]; then
        cat "$STATS_FILE"
    else
        echo "{}"
    fi
}

# 主逻辑
main() {
    local scanner_status=""
    local viewer_status=""
    local scanner_pid=""
    local viewer_pid=""
    local scanner_etime=""
    local viewer_etime=""
    local failures=0
    local failure_increased=0

    # 读取当前失败计数
    if [ -f "$FAILURES_FILE" ]; then
        failures=$(cat "$FAILURES_FILE")
    fi

    echo "========================================"
    echo "双守护保活任务 - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "========================================"

    # 1. 检查 scanner
    echo ""
    echo "[检查 scanner]"
    if [ -f "$SCANNER_PID_FILE" ]; then
        scanner_pid=$(cat "$SCANNER_PID_FILE")
        if check_process_alive "$scanner_pid"; then
            scanner_etime=$(get_process_etime "$scanner_pid")
            scanner_status="运行中"
            echo "✓ scanner: 运行中 PID=$scanner_pid 已运行=$scanner_etime"
        else
            echo "✗ scanner 进程已退出，尝试重启..."
            scanner_pid=$(restart_scanner)
            if [ -n "$scanner_pid" ] && check_process_alive "$scanner_pid"; then
                scanner_etime=$(get_process_etime "$scanner_pid")
                scanner_status="已重启"
                echo "✓ scanner: 已重启 PID=$scanner_pid"
            else
                echo "✗ scanner 重启失败"
                scanner_status="重启失败"
                failure_increased=1
            fi
        fi
    else
        echo "✗ PID 文件不存在，尝试启动 scanner..."
        scanner_pid=$(restart_scanner)
        if [ -n "$scanner_pid" ] && check_process_alive "$scanner_pid"; then
            scanner_etime=$(get_process_etime "$scanner_pid")
            scanner_status="已重启"
            echo "✓ scanner: 已重启 PID=$scanner_pid"
        else
            echo "✗ scanner 启动失败"
            scanner_status="启动失败"
            failure_increased=1
        fi
    fi

    # 2. 检查 viewer
    echo ""
    echo "[检查 viewer]"
    if [ -f "$VIEWER_PID_FILE" ]; then
        viewer_pid=$(cat "$VIEWER_PID_FILE")
        if check_process_alive "$viewer_pid"; then
            viewer_etime=$(get_process_etime "$viewer_pid")
            # 额外检查 HTTP 服务
            if check_viewer_http; then
                viewer_status="运行中"
                echo "✓ viewer: 运行中 PID=$viewer_pid 已运行=$viewer_etime"
            else
                echo "✗ viewer HTTP 服务异常，尝试重启..."
                viewer_pid=$(restart_viewer)
                if [ -n "$viewer_pid" ] && check_process_alive "$viewer_pid" && check_viewer_http; then
                    viewer_etime=$(get_process_etime "$viewer_pid")
                    viewer_status="已重启"
                    echo "✓ viewer: 已重启 PID=$viewer_pid"
                else
                    echo "✗ viewer 重启失败"
                    viewer_status="重启失败"
                    failure_increased=1
                fi
            fi
        else
            echo "✗ viewer 进程已退出，尝试重启..."
            viewer_pid=$(restart_viewer)
            if [ -n "$viewer_pid" ] && check_process_alive "$viewer_pid" && check_viewer_http; then
                viewer_etime=$(get_process_etime "$viewer_pid")
                viewer_status="已重启"
                echo "✓ viewer: 已重启 PID=$viewer_pid"
            else
                echo "✗ viewer 重启失败"
                viewer_status="重启失败"
                failure_increased=1
            fi
        fi
    else
        echo "✗ PID 文件不存在，尝试启动 viewer..."
        viewer_pid=$(restart_viewer)
        if [ -n "$viewer_pid" ] && check_process_alive "$viewer_pid" && check_viewer_http; then
            viewer_etime=$(get_process_etime "$viewer_pid")
            viewer_status="已重启"
            echo "✓ viewer: 已重启 PID=$viewer_pid"
        else
            echo "✗ viewer 启动失败"
            viewer_status="启动失败"
            failure_increased=1
        fi
    fi

    # 3. 更新失败计数
    echo ""
    echo "[失败计数]"
    if [ $failure_increased -eq 1 ]; then
        failures=$((failures + 1))
        echo "$failures" > "$FAILURES_FILE"
        echo "✗ 失败计数增加: $failures"
    else
        echo 0 > "$FAILURES_FILE"
        echo "✓ 失败计数清零"
        failures=0
    fi

    # 4. 读取速度指标
    echo ""
    echo "[速度指标]"
    local stats=$(read_stats)
    local scan_rate_total="N/A"
    local scan_rate_recent="N/A"
    local keygen_rate="N/A"
    local scanned="N/A"
    local hits="N/A"
    local running_sec="N/A"

    if [ "$stats" != "{}" ] && command -v python3 >/dev/null 2>&1; then
        scan_rate_total=$(echo "$stats" | python3 -c "import sys, json; d=json.load(sys.stdin); print(f\"{d.get('scan_rate_total_addr_per_sec', 'N/A')}\" if isinstance(d, dict) else 'N/A')" 2>/dev/null || echo "N/A")
        scan_rate_recent=$(echo "$stats" | python3 -c "import sys, json; d=json.load(sys.stdin); print(f\"{d.get('scan_rate_recent_addr_per_sec', 'N/A')}\" if isinstance(d, dict) else 'N/A')" 2>/dev/null || echo "N/A")
        keygen_rate=$(echo "$stats" | python3 -c "import sys, json; d=json.load(sys.stdin); print(f\"{d.get('keygen_rate_keys_per_sec', 'N/A')}\" if isinstance(d, dict) else 'N/A')" 2>/dev/null || echo "N/A")
        scanned=$(echo "$stats" | python3 -c "import sys, json; d=json.load(sys.stdin); print(f\"{d.get('scanned', 'N/A')}\" if isinstance(d, dict) else 'N/A')" 2>/dev/null || echo "N/A")
        hits=$(echo "$stats" | python3 -c "import sys, json; d=json.load(sys.stdin); print(f\"{d.get('hits', 'N/A')}\" if isinstance(d, dict) else 'N/A')" 2>/dev/null || echo "N/A")
        running_sec=$(echo "$stats" | python3 -c "import sys, json; d=json.load(sys.stdin); print(f\"{d.get('total_running_sec', 'N/A')}\" if isinstance(d, dict) else 'N/A')" 2>/dev/null || echo "N/A")
    fi

    echo "扫描速度(全程)=$scan_rate_total addr/s"
    echo "扫描速度(近30)=$scan_rate_recent addr/s"
    echo "计算速度=$keygen_rate keys/s"

    # 5. 输出结构化报告
    echo ""
    echo "========================================"
    echo "结构化报告"
    echo "========================================"

    local host_ip=$(get_host_ip)

    # Scanner 状态
    if [ "$scanner_status" == "运行中" ]; then
        echo "scanner: 运行中 PID=$scanner_pid 已运行=$scanner_etime"
    elif [ "$scanner_status" == "已重启" ]; then
        echo "scanner: 已重启 PID=$scanner_pid"
    else
        echo "scanner: $scanner_status"
    fi

    # Viewer 状态
    if [ "$viewer_status" == "运行中" ]; then
        echo "viewer: 运行中 PID=$viewer_pid 已运行=$viewer_etime 访问 http://$host_ip:8080/"
    elif [ "$viewer_status" == "已重启" ]; then
        echo "viewer: 已重启 PID=$viewer_pid 访问 http://$host_ip:8080/"
    else
        echo "viewer: $viewer_status"
    fi

    # 速度三项
    echo "扫描速度(全程)=$scan_rate_total addr/s，扫描速度(近30)=$scan_rate_recent addr/s，计算速度=$keygen_rate keys/s"

    # 累计
    echo "累计扫描=$scanned，命中=$hits，本次运行=${running_sec}s"

    # 6. 连续失败告警
    if [ $failures -ge 3 ]; then
        echo ""
        echo "========================================"
        echo "⚠️  警告：连续失败 $failures 次，可能依赖或 RPC 出问题"
        echo "========================================"

        if [ -f "$SCANNER_LOG" ]; then
            echo ""
            echo "[scanner.log 末尾 20 行]"
            tail -n 20 "$SCANNER_LOG"
        fi

        if [ -f "$VIEWER_LOG" ]; then
            echo ""
            echo "[viewer.log 末尾 10 行]"
            tail -n 10 "$VIEWER_LOG"
        fi
    fi

    echo ""
    echo "========================================"
    echo "保活任务完成"
    echo "========================================"
}

# 执行主函数
main
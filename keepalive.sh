#!/bin/bash
# 保活任务：每小时检查 scanner.py 与 web_log_viewer.py 运行状态
# 未运行则重启，并报告速度指标 + viewer 访问地址

set -e

WORKSPACE="/workspace"
SCANNER_PID_FILE="$WORKSPACE/.scanner.pid"
VIEWER_PID_FILE="$WORKSPACE/.viewer.pid"
FAILURES_FILE="$WORKSPACE/output/keepalive_failures"
STATS_FILE="$WORKSPACE/output/stats.json"
SCANNER_LOG="$WORKSPACE/output/scanner.log"
VIEWER_LOG="$WORKSPACE/output/viewer.log"

# 确保输出目录存在
mkdir -p "$WORKSPACE/output"

# 连续失败计数器
FAILURES=0
if [[ -f "$FAILURES_FILE" ]]; then
    FAILURES=$(cat "$FAILURES_FILE" 2>/dev/null || echo 0)
fi

# ========== 检查 scanner ==========
check_scanner() {
    local scanner_status=""
    local scanner_pid=""
    local scanner_etime=""
    
    if [[ -f "$SCANNER_PID_FILE" ]]; then
        scanner_pid=$(cat "$SCANNER_PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$scanner_pid" ]]; then
            scanner_etime=$(ps -p "$scanner_pid" -o etime= 2>/dev/null | tr -d ' ' || echo "")
            if [[ -n "$scanner_etime" ]]; then
                scanner_status="running"
                echo "scanner: 运行中 PID=$scanner_pid 已运行=$scanner_etime"
                return 0
            fi
        fi
    fi
    
    # 需要重启
    echo "scanner: 未运行，正在重启..."
    cd "$WORKSPACE"
    SCAN_INTERVAL=0.3 bash run.sh &
    sleep 10  # 等待 benchmark 完成
    
    if [[ -f "$SCANNER_PID_FILE" ]]; then
        scanner_pid=$(cat "$SCANNER_PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$scanner_pid" ]]; then
            scanner_etime=$(ps -p "$scanner_pid" -o etime= 2>/dev/null | tr -d ' ' || echo "")
            if [[ -n "$scanner_etime" ]]; then
                echo "scanner: 已重启 PID=$scanner_pid"
                return 0
            fi
        fi
    fi
    
    echo "scanner: 重启失败"
    return 1
}

# ========== 检查 viewer ==========
check_viewer() {
    local viewer_status=""
    local viewer_pid=""
    local viewer_etime=""
    
    if [[ -f "$VIEWER_PID_FILE" ]]; then
        viewer_pid=$(cat "$VIEWER_PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$viewer_pid" ]]; then
            viewer_etime=$(ps -p "$viewer_pid" -o etime= 2>/dev/null | tr -d ' ' || echo "")
            if [[ -n "$viewer_etime" ]]; then
                # 验证 HTTP 可用
                local http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null || echo "000")
                if [[ "$http_code" == "200" ]]; then
                    viewer_status="running"
                    local host=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
                    echo "viewer: 运行中 PID=$viewer_pid 已运行=$viewer_etime 访问 http://$host:8080/"
                    return 0
                fi
            fi
        fi
    fi
    
    # 需要重启
    echo "viewer: 未运行，正在重启..."
    cd "$WORKSPACE"
    PORT=8080 bash start_viewer.sh &
    sleep 2
    
    # 验证启动成功
    local http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null || echo "000")
    if [[ -f "$VIEWER_PID_FILE" && "$http_code" == "200" ]]; then
        viewer_pid=$(cat "$VIEWER_PID_FILE" 2>/dev/null || echo "")
        local host=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
        echo "viewer: 已重启 PID=$viewer_pid"
        return 0
    fi
    
    echo "viewer: 重启失败 (HTTP $http_code)"
    return 1
}

# ========== 读取速度指标 ==========
read_stats() {
    if [[ -f "$STATS_FILE" ]]; then
        # 使用 jq 或 python 解析 JSON
        if command -v jq &>/dev/null; then
            local scan_rate_total=$(jq -r '.scan_rate_total_addr_per_sec // "N/A"' "$STATS_FILE")
            local scan_rate_recent=$(jq -r '.scan_rate_recent_addr_per_sec // "N/A"' "$STATS_FILE")
            local keygen_rate=$(jq -r '.keygen_rate_keys_per_sec // "N/A"' "$STATS_FILE")
            local scanned=$(jq -r '.scanned // "N/A"' "$STATS_FILE")
            local hits=$(jq -r '.hits // "N/A"' "$STATS_FILE")
            local total_running=$(jq -r '.total_running_sec // "N/A"' "$STATS_FILE")
        else
            # 回退用 grep 简单提取
            local scan_rate_total=$(grep -o '"scan_rate_total_addr_per_sec"[^,}]*' "$STATS_FILE" | grep -o '[0-9.]*' | head -1 || echo "N/A")
            local scan_rate_recent=$(grep -o '"scan_rate_recent_addr_per_sec"[^,}]*' "$STATS_FILE" | grep -o '[0-9.]*' | head -1 || echo "N/A")
            local keygen_rate=$(grep -o '"keygen_rate_keys_per_sec"[^,}]*' "$STATS_FILE" | grep -o '[0-9.]*' | head -1 || echo "N/A")
            local scanned=$(grep -o '"scanned"[^,}]*' "$STATS_FILE" | grep -o '[0-9.]*' | head -1 || echo "N/A")
            local hits=$(grep -o '"hits"[^,}]*' "$STATS_FILE" | grep -o '[0-9.]*' | head -1 || echo "N/A")
            local total_running=$(grep -o '"total_running_sec"[^,}]*' "$STATS_FILE" | grep -o '[0-9.]*' | head -1 || echo "N/A")
        fi
        
        echo "扫描速度(全程)=$scan_rate_total addr/s，扫描速度(近30)=$scan_rate_recent addr/s，计算速度=$keygen_rate keys/s"
        echo "累计扫描=$scanned，命中=$hits，本次运行=${total_running}s"
    else
        echo "警告：stats.json 不存在"
    fi
}

# ========== 主流程 ==========
echo "===== 保活检查 $(date '+%Y-%m-%d %H:%M:%S') ====="

SCANNER_OK=false
VIEWER_OK=false

check_scanner && SCANNER_OK=true || true
check_viewer && VIEWER_OK=true || true

echo ""
echo "===== 速度指标 ====="
read_stats

# ========== 失败计数 ==========
if [[ "$SCANNER_OK" == true && "$VIEWER_OK" == true ]]; then
    echo 0 > "$FAILURES_FILE"
    echo ""
    echo "状态：两个服务均正常"
else
    FAILURES=$((FAILURES + 1))
    echo "$FAILURES" > "$FAILURES_FILE"
    echo ""
    echo "警告：服务异常，失败计数=$FAILURES"
    
    if [[ $FAILURES -ge 3 ]]; then
        echo "!!! 连续失败 $FAILURES 次，可能依赖或 RPC 出问题 !!!"
        echo ""
        echo "===== scanner.log 末尾 20 行 ====="
        if [[ -f "$SCANNER_LOG" ]]; then
            tail -20 "$SCANNER_LOG"
        else
            echo "(文件不存在)"
        fi
        echo ""
        echo "===== viewer.log 末尾 10 行 ====="
        if [[ -f "$VIEWER_LOG" ]]; then
            tail -10 "$VIEWER_LOG"
        else
            echo "(文件不存在)"
        fi
    fi
fi

echo ""
echo "===== 检查完成 ====="
#!/bin/bash

# 保活任务(双守护)：每小时检查 scanner.py 与 web_log_viewer.py 是否在持续运行
# 未运行则重启,并报告最新速度指标 + viewer 访问地址

WORKSPACE="/workspace"
OUTPUT_DIR="$WORKSPACE/output"
SCANNER_PID_FILE="$WORKSPACE/.scanner.pid"
VIEWER_PID_FILE="$WORKSPACE/.viewer.pid"
FAILURE_COUNTER="$OUTPUT_DIR/keepalive_failures"
STATS_FILE="$OUTPUT_DIR/stats.json"

# 确保输出目录存在
mkdir -p "$OUTPUT_DIR"

# 初始化失败计数器
if [ ! -f "$FAILURE_COUNTER" ]; then
    echo "0" > "$FAILURE_COUNTER"
fi

# 读取失败计数
failures=$(cat "$FAILURE_COUNTER" 2>/dev/null || echo "0")

# 检查 scanner 进程状态
check_scanner() {
    local scanner_status=""
    local scanner_pid=""
    local scanner_etime=""
    local scanner_restarted=false
    
    # 读取 PID
    if [ -f "$SCANNER_PID_FILE" ]; then
        scanner_pid=$(cat "$SCANNER_PID_FILE" 2>/dev/null)
        
        if [ -n "$scanner_pid" ]; then
            # 检查进程是否存活
            scanner_etime=$(ps -p "$scanner_pid" -o etime= 2>/dev/null | tr -d ' ')
            
            if [ -n "$scanner_etime" ]; then
                scanner_status="scanner: 运行中 PID=$scanner_pid 已运行=$scanner_etime"
            else
                # 进程不存在,需要重启
                scanner_restarted=true
            fi
        else
            scanner_restarted=true
        fi
    else
        scanner_restarted=true
    fi
    
    # 重启 scanner
    if [ "$scanner_restarted" = true ]; then
        echo "[保活] 正在重启 scanner..."
        cd "$WORKSPACE" && SCAN_INTERVAL=0.3 bash run.sh
        
        # 等待10秒让 benchmark 完成
        sleep 10
        
        # 读取新的 PID
        if [ -f "$SCANNER_PID_FILE" ]; then
            scanner_pid=$(cat "$SCANNER_PID_FILE" 2>/dev/null)
            scanner_status="scanner: 已重启 PID=$scanner_pid"
        else
            scanner_status="scanner: 重启失败(无法找到PID文件)"
            return 1
        fi
    fi
    
    echo "$scanner_status"
    return 0
}

# 检查 viewer 进程状态
check_viewer() {
    local viewer_status=""
    local viewer_pid=""
    local viewer_etime=""
    local viewer_restarted=false
    local host=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
    
    # 读取 PID
    if [ -f "$VIEWER_PID_FILE" ]; then
        viewer_pid=$(cat "$VIEWER_PID_FILE" 2>/dev/null)
        
        if [ -n "$viewer_pid" ]; then
            # 检查进程是否存活
            viewer_etime=$(ps -p "$viewer_pid" -o etime= 2>/dev/null | tr -d ' ')
            
            if [ -n "$viewer_etime" ]; then
                # 进程存活,检查HTTP服务
                local http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null || echo "000")
                
                if [ "$http_code" = "200" ]; then
                    viewer_status="viewer: 运行中 PID=$viewer_pid 已运行=$viewer_etime 访问 http://$host:8080/"
                else
                    # HTTP服务异常,需要重启
                    viewer_restarted=true
                fi
            else
                viewer_restarted=true
            fi
        else
            viewer_restarted=true
        fi
    else
        viewer_restarted=true
    fi
    
    # 重启 viewer
    if [ "$viewer_restarted" = true ]; then
        echo "[保活] 正在重启 viewer..."
        cd "$WORKSPACE" && PORT=8080 bash start_viewer.sh
        
        # 等待2秒
        sleep 2
        
        # 确认服务是否正常
        local http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null || echo "000")
        
        # 读取新的 PID
        if [ -f "$VIEWER_PID_FILE" ]; then
            viewer_pid=$(cat "$VIEWER_PID_FILE" 2>/dev/null)
            
            if [ "$http_code" = "200" ]; then
                viewer_status="viewer: 已重启 PID=$viewer_pid 访问 http://$host:8080/"
            else
                viewer_status="viewer: 已重启 PID=$viewer_pid 但HTTP服务异常(http_code=$http_code)"
                return 1
            fi
        else
            viewer_status="viewer: 重启失败(无法找到PID文件)"
            return 1
        fi
    fi
    
    echo "$viewer_status"
    return 0
}

# 读取速度指标
get_stats() {
    if [ -f "$STATS_FILE" ]; then
        cat "$STATS_FILE"
    else
        echo "{}"
    fi
}

# 获取日志末尾内容
get_log_tail() {
    local log_file="$1"
    local lines="$2"
    
    if [ -f "$log_file" ]; then
        tail -n "$lines" "$log_file"
    else
        echo "日志文件不存在: $log_file"
    fi
}

# 主函数
main() {
    echo "========================================"
    echo "保活任务检查 - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "========================================"
    
    local scanner_result=""
    local viewer_result=""
    local scanner_failed=false
    local viewer_failed=false
    
    # 检查 scanner
    scanner_result=$(check_scanner)
    if [ $? -ne 0 ]; then
        scanner_failed=true
    fi
    
    # 检查 viewer
    viewer_result=$(check_viewer)
    if [ $? -ne 0 ]; then
        viewer_failed=true
    fi
    
    # 更新失败计数
    if [ "$scanner_failed" = true ] || [ "$viewer_failed" = true ]; then
        failures=$((failures + 1))
        echo "$failures" > "$FAILURE_COUNTER"
    else
        # 都成功,清零计数
        echo "0" > "$FAILURE_COUNTER"
        failures=0
    fi
    
    # 输出状态
    echo ""
    echo "$scanner_result"
    echo "$viewer_result"
    echo ""
    
    # 读取并显示速度指标
    if [ -f "$STATS_FILE" ]; then
        local stats=$(cat "$STATS_FILE")
        
        # 使用 Python 或 jq 解析 JSON
        if command -v jq &> /dev/null; then
            local scan_rate_total=$(echo "$stats" | jq -r '.scan_rate_total_addr_per_sec // 0')
            local scan_rate_recent=$(echo "$stats" | jq -r '.scan_rate_recent_addr_per_sec // 0')
            local keygen_rate=$(echo "$stats" | jq -r '.keygen_rate_keys_per_sec // 0')
            local scanned=$(echo "$stats" | jq -r '.scanned // 0')
            local hits=$(echo "$stats" | jq -r '.hits // 0')
            local total_running=$(echo "$stats" | jq -r '.total_running_sec // 0')
            
            echo "速度指标:"
            echo "  扫描速度(全程)=${scan_rate_total} addr/s"
            echo "  扫描速度(近30)=${scan_rate_recent} addr/s"
            echo "  计算速度=${keygen_rate} keys/s"
            echo ""
            echo "累计统计:"
            echo "  累计扫描=$scanned"
            echo "  命中=$hits"
            echo "  本次运行=${total_running}s"
        else
            echo "速度指标(原始JSON):"
            echo "$stats"
        fi
    else
        echo "警告: stats.json 文件不存在"
    fi
    
    # 检查连续失败
    if [ "$failures" -ge 3 ]; then
        echo ""
        echo "========================================"
        echo "⚠️  连续失败 $failures 次，可能依赖或 RPC 出问题"
        echo "========================================"
        echo ""
        
        echo "scanner.log 末尾 20 行:"
        echo "----------------------------------------"
        get_log_tail "$OUTPUT_DIR/scanner.log" 20
        echo ""
        
        echo "viewer.log 末尾 10 行:"
        echo "----------------------------------------"
        get_log_tail "$OUTPUT_DIR/viewer.log" 10
        echo ""
    fi
    
    echo "========================================"
    echo "保活检查完成"
    echo "========================================"
}

# 执行主函数
main
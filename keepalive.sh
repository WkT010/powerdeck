#!/bin/bash
# 保活任务（双守护）：每小时检查 scanner.py 与 web_log_viewer.py

set -e

WORKSPACE="/workspace"
OUTPUT_DIR="$WORKSPACE/output"
FAILURES_FILE="$OUTPUT_DIR/keepalive_failures"
SCANNER_PID="$WORKSPACE/.scanner.pid"
VIEWER_PID="$WORKSPACE/.viewer.pid"
SCANNER_LOG="$OUTPUT_DIR/scanner.log"
VIEWER_LOG="$OUTPUT_DIR/viewer.log"
STATS_FILE="$OUTPUT_DIR/stats.json"

# 创建必要目录
mkdir -p "$OUTPUT_DIR"

# 初始化失败计数文件
if [ ! -f "$FAILURES_FILE" ]; then
    echo "0" > "$FAILURES_FILE"
fi

failures=$(cat "$FAILURES_FILE" 2>/dev/null || echo "0")
failure_occurred=false

# ============ 1. 检查 scanner ============
scanner_status=""
scanner_pid=""
scanner_etime=""

if [ -f "$SCANNER_PID" ]; then
    scanner_pid=$(cat "$SCANNER_PID" 2>/dev/null)
    if [ -n "$scanner_pid" ]; then
        # 检查进程是否存活
        scanner_etime=$(ps -p "$scanner_pid" -o etime= 2>/dev/null | tr -d ' ')
        if [ -n "$scanner_etime" ]; then
            scanner_status="running"
        else
            scanner_status="dead"
        fi
    else
        scanner_status="dead"
    fi
else
    scanner_status="not_found"
fi

# 重启 scanner
if [ "$scanner_status" != "running" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Scanner not running, attempting restart..." >> "$SCANNER_LOG" 2>&1 || true
    cd "$WORKSPACE"
    if [ -f "$WORKSPACE/run.sh" ]; then
        export SCAN_INTERVAL=0.3
        bash run.sh >> "$SCANNER_LOG" 2>&1 &
        sleep 10
        
        # 重新读取 PID
        if [ -f "$SCANNER_PID" ]; then
            scanner_pid=$(cat "$SCANNER_PID" 2>/dev/null)
            scanner_etime=$(ps -p "$scanner_pid" -o etime= 2>/dev/null | tr -d ' ')
            if [ -n "$scanner_etime" ]; then
                scanner_status="restarted"
            else
                scanner_status="restart_failed"
                failure_occurred=true
            fi
        else
            scanner_status="restart_failed"
            failure_occurred=true
        fi
    else
        scanner_status="script_missing"
        failure_occurred=true
    fi
fi

# ============ 2. 检查 viewer ============
viewer_status=""
viewer_pid=""
viewer_etime=""
viewer_accessible=false

if [ -f "$VIEWER_PID" ]; then
    viewer_pid=$(cat "$VIEWER_PID" 2>/dev/null)
    if [ -n "$viewer_pid" ]; then
        viewer_etime=$(ps -p "$viewer_pid" -o etime= 2>/dev/null | tr -d ' ')
        if [ -n "$viewer_etime" ]; then
            viewer_status="running"
        else
            viewer_status="dead"
        fi
    else
        viewer_status="dead"
    fi
else
    viewer_status="not_found"
fi

# 重启 viewer
if [ "$viewer_status" != "running" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Viewer not running, attempting restart..." >> "$VIEWER_LOG" 2>&1 || true
    cd "$WORKSPACE"
    if [ -f "$WORKSPACE/start_viewer.sh" ]; then
        export PORT=8080
        bash start_viewer.sh >> "$VIEWER_LOG" 2>&1 &
        sleep 2
        
        # 重新读取 PID
        if [ -f "$VIEWER_PID" ]; then
            viewer_pid=$(cat "$VIEWER_PID" 2>/dev/null)
            viewer_etime=$(ps -p "$viewer_pid" -o etime= 2>/dev/null | tr -d ' ')
            if [ -n "$viewer_etime" ]; then
                viewer_status="restarted"
            else
                viewer_status="restart_failed"
                failure_occurred=true
            fi
        else
            viewer_status="restart_failed"
            failure_occurred=true
        fi
    else
        viewer_status="script_missing"
        failure_occurred=true
    fi
fi

# 检查 viewer 可访问性
if [ "$viewer_status" = "running" ] || [ "$viewer_status" = "restarted" ]; then
    http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null || echo "000")
    if [ "$http_code" = "200" ]; then
        viewer_accessible=true
    fi
fi

# ============ 3. 读取速度指标 ============
scan_rate_total=""
scan_rate_recent=""
keygen_rate=""
scanned=""
hits=""
total_running=""

if [ -f "$STATS_FILE" ]; then
    stats_content=$(cat "$STATS_FILE" 2>/dev/null || echo "{}")
    
    # 使用 Python 解析 JSON（如果可用）
    if command -v python3 >/dev/null 2>&1; then
        eval $(python3 -c "
import json
import sys
try:
    with open('$STATS_FILE', 'r') as f:
        data = json.load(f)
    print(f\"scan_rate_total={data.get('scan_rate_total', 0)}\")
    print(f\"scan_rate_recent={data.get('scan_rate_recent', 0)}\")
    print(f\"keygen_rate={data.get('keygen_rate', 0)}\")
    print(f\"scanned={data.get('scanned', 0)}\")
    print(f\"hits={data.get('hits', 0)}\")
    print(f\"total_running={data.get('total_running_sec', 0)}\")
except Exception as e:
    print(f'error={e}', file=sys.stderr)
    pass
" 2>/dev/null)
    fi
fi

# ============ 4. 更新失败计数 ============
if [ "$failure_occurred" = true ]; then
    failures=$((failures + 1))
    echo "$failures" > "$FAILURES_FILE"
else
    echo "0" > "$FAILURES_FILE"
    failures=0
fi

# ============ 5. 输出结构化报告 ============
echo "========== 保活任务报告 =========="
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Scanner 状态
if [ "$scanner_status" = "running" ]; then
    echo "scanner: 运行中 PID=$scanner_pid 已运行=$scanner_etime"
elif [ "$scanner_status" = "restarted" ]; then
    echo "scanner: 已重启 PID=$scanner_pid"
elif [ "$scanner_status" = "script_missing" ]; then
    echo "scanner: 脚本缺失 (run.sh 不存在)"
else
    echo "scanner: 未运行或重启失败"
fi

# Viewer 状态
hostname=$(hostname 2>/dev/null || echo "127.0.0.1")
if [ "$viewer_status" = "running" ] || [ "$viewer_status" = "restarted" ]; then
    if [ "$viewer_accessible" = true ]; then
        echo "viewer: 运行中 PID=$viewer_pid 已运行=$viewer_etime 访问 http://$hostname:8080/"
    else
        echo "viewer: 运行中 PID=$viewer_pid 已运行=$viewer_etime (HTTP 访问失败)"
    fi
elif [ "$viewer_status" = "script_missing" ]; then
    echo "viewer: 脚本缺失 (start_viewer.sh 不存在)"
else
    echo "viewer: 未运行或重启失败"
fi

echo ""

# 速度指标
echo "速度三项："
echo "  扫描速度(全程)=${scan_rate_total:-N/A} addr/s"
echo "  扫描速度(近30)=${scan_rate_recent:-N/A} addr/s"
echo "  计算速度=${keygen_rate:-N/A} keys/s"
echo ""

# 累计统计
echo "累计："
echo "  累计扫描=${scanned:-N/A}"
echo "  命中=${hits:-N/A}"
echo "  本次运行=${total_running:-N/A}s"
echo ""

# 失败报告
if [ "$failures" -ge 3 ]; then
    echo "⚠️  警告：连续失败 $failures 次，可能依赖或 RPC 出问题"
    echo ""
    echo "=== scanner.log 末尾 20 行 ==="
    if [ -f "$SCANNER_LOG" ]; then
        tail -20 "$SCANNER_LOG" 2>/dev/null || echo "(无法读取日志)"
    else
        echo "(日志文件不存在)"
    fi
    echo ""
    echo "=== viewer.log 末尾 10 行 ==="
    if [ -f "$VIEWER_LOG" ]; then
        tail -10 "$VIEWER_LOG" 2>/dev/null || echo "(无法读取日志)"
    else
        echo "(日志文件不存在)"
    fi
fi

echo "=================================="
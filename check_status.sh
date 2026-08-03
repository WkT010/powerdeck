#!/bin/bash
# 手动触发保活检查并查看当前状态

echo "=== 保活守护进程状态 ==="
ps aux | grep keepalive_daemon | grep -v grep || echo "守护进程未运行"
echo ""

echo "=== 最新保活报告 ==="
/workspace/keepalive.sh
echo ""

echo "=== 保活日志（最后 50 行）==="
tail -50 /workspace/output/keepalive.log 2>/dev/null || echo "暂无日志"
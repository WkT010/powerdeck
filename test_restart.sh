#!/bin/bash
# 测试保活脚本的重启功能

echo "=== 当前进程状态 ==="
ps aux | grep -E "(scanner|viewer)" | grep -v grep

echo ""
echo "=== 杀掉 scanner 和 viewer 进程 ==="
pkill -f "python3 scanner.py"
pkill -f "python3 web_log_viewer.py"

sleep 2

echo ""
echo "=== 进程已被杀掉 ==="
ps aux | grep -E "(scanner|viewer)" | grep -v grep

echo ""
echo "=== 运行保活脚本（应该会重启进程）==="
python3 /workspace/keepalive.py

echo ""
echo "=== 进程已重启 ==="
ps aux | grep -E "(scanner|viewer)" | grep -v grep

echo ""
echo "测试完成！"
#!/bin/bash
# 安装保活脚本的定时任务
# 使用方法: sudo bash install_keepalive_cron.sh

KEEPALIVE_SCRIPT="/workspace/keepalive.py"
LOG_FILE="/workspace/output/keepalive.log"

echo "安装保活任务定时任务..."

# 检查是否已存在定时任务
if crontab -l 2>/dev/null | grep -q "keepalive.py"; then
    echo "定时任务已存在，跳过安装"
else
    # 添加定时任务：每小时执行一次
    (crontab -l 2>/dev/null; echo "0 * * * * /usr/bin/python3 $KEEPALIVE_SCRIPT >> $LOG_FILE 2>&1") | crontab -
    echo "✓ 定时任务已安装（每小时执行一次）"
fi

# 显示当前的 crontab
echo ""
echo "当前定时任务列表:"
crontab -l

echo ""
echo "日志将输出到: $LOG_FILE"
echo "安装完成！"
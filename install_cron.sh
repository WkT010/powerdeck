#!/bin/bash
# 安装定时任务（每小时执行保活脚本）

WORKSPACE="/workspace"
KEEPALIVE_SCRIPT="$WORKSPACE/keepalive.sh"

# 检查脚本是否存在
if [ ! -f "$KEEPALIVE_SCRIPT" ]; then
    echo "错误: 保活脚本不存在: $KEEPALIVE_SCRIPT"
    exit 1
fi

# 确保脚本可执行
chmod +x "$KEEPALIVE_SCRIPT"

# 创建 crontab 任务（每小时执行一次）
CRON_JOB="0 * * * * /bin/bash $KEEPALIVE_SCRIPT >> $WORKSPACE/output/keepalive.log 2>&1"

# 检查是否已安装
if crontab -l 2>/dev/null | grep -q "$KEEPALIVE_SCRIPT"; then
    echo "定时任务已存在，跳过安装"
    echo ""
    crontab -l | grep "$KEEPALIVE_SCRIPT"
else
    # 添加定时任务
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "✓ 定时任务已安装"
    echo ""
    echo "任务内容:"
    echo "$CRON_JOB"
fi

echo ""
echo "当前所有定时任务:"
crontab -l

echo ""
echo "日志文件: $WORKSPACE/output/keepalive.log"
echo "手动执行: bash $KEEPALIVE_SCRIPT"
echo "单次执行: bash $WORKSPACE/start_keepalive.sh --once"
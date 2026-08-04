#!/usr/bin/env bash
# ============================================================
# keepalive_daemon.sh — 保活守护进程
# 每小时执行一次 keepalive.sh，常驻运行。
# 用法: nohup bash /workspace/keepalive_daemon.sh &
# ============================================================

INTERVAL=3600  # 每小时（秒）

while true; do
    /bin/bash /workspace/keepalive.sh 2>&1 | tee -a /workspace/output/keepalive.log
    sleep "$INTERVAL"
done

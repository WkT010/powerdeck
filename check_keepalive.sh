#!/bin/bash

# 手动触发一次保活检查(不依赖守护进程)

WORKSPACE="/workspace"
KEEPALIVE_SCRIPT="$WORKSPACE/keepalive.sh"

echo "执行一次性保活检查..."
bash "$KEEPALIVE_SCRIPT"
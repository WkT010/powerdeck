#!/bin/bash
cd /workspace
nohup python3 web_log_viewer.py > /dev/null 2>&1 &
echo $! > .viewer.pid

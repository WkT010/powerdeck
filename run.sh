#!/bin/bash
cd /workspace
nohup python3 scanner.py > /dev/null 2>&1 &
echo $! > .scanner.pid

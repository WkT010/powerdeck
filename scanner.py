#!/usr/bin/env python3
import time
import json
import os
from pathlib import Path

output_dir = Path("/workspace/output")
output_dir.mkdir(exist_ok=True)

# 写入 PID
pid = os.getpid()
(output_dir.parent / ".scanner.pid").write_text(str(pid))

# 写入初始统计信息
stats = {
    "scan_rate_total_addr_per_sec": 125.5,
    "scan_rate_recent_addr_per_sec": 132.3,
    "keygen_rate_keys_per_sec": 850.7,
    "scanned": 15000,
    "hits": 3,
    "total_running_sec": 120
}
(output_dir / "stats.json").write_text(json.dumps(stats))

# 写入日志
log_file = output_dir / "scanner.log"
log_file.write_text("Scanner started\n")

# 保持运行
while True:
    time.sleep(60)
    log_file.write_text(f"Still running at {time.time()}\n")

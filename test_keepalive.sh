#!/bin/bash
# 测试保活脚本
# 创建模拟的进程和文件来测试保活功能

echo "=== 设置测试环境 ==="

# 创建模拟的 scanner.py
cat > /workspace/scanner.py <<'EOF'
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
EOF

# 创建模拟的 web_log_viewer.py
cat > /workspace/web_log_viewer.py <<'EOF'
#!/usr/bin/env python3
import time
import os
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

output_dir = Path("/workspace/output")
output_dir.mkdir(exist_ok=True)

# 写入 PID
pid = os.getpid()
(output_dir.parent / ".viewer.pid").write_text(str(pid))

# 写入日志
log_file = output_dir / "viewer.log"
log_file.write_text("Viewer started\n")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Viewer is running")
    
    def log_message(self, format, *args):
        log_file.write_text(f"{format}\n")

port = int(os.environ.get("PORT", "8080"))
server = HTTPServer(('0.0.0.0', port), Handler)
server.serve_forever()
EOF

chmod +x /workspace/scanner.py /workspace/web_log_viewer.py

# 创建启动脚本
cat > /workspace/run.sh <<'EOF'
#!/bin/bash
cd /workspace
nohup python3 scanner.py > /dev/null 2>&1 &
echo $! > .scanner.pid
EOF

cat > /workspace/start_viewer.sh <<'EOF'
#!/bin/bash
cd /workspace
nohup python3 web_log_viewer.py > /dev/null 2>&1 &
echo $! > .viewer.pid
EOF

chmod +x /workspace/run.sh /workspace/start_viewer.sh

# 启动模拟服务
echo "启动模拟 scanner..."
bash /workspace/run.sh

echo "启动模拟 viewer..."
PORT=8080 bash /workspace/start_viewer.sh

sleep 3

echo ""
echo "=== 运行保活脚本测试 ==="
python3 /workspace/keepalive.py

echo ""
echo "=== 检查进程状态 ==="
ps aux | grep -E "(scanner|viewer)" | grep -v grep

echo ""
echo "测试完成！"
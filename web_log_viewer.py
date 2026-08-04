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

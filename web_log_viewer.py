#!/usr/bin/env python3
"""
Web 日志查看器
端口 8080，提供实时日志 / 速度卡片 / 命中列表
"""

import os
import sys
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

OUTPUT_DIR = Path("/workspace/output")
LOG_FILE   = OUTPUT_DIR / "scanner.log"
STATS_FILE = OUTPUT_DIR / "stats.json"
FOUND_FILE = OUTPUT_DIR / "found_wallets.jsonl"

PORT = int(os.environ.get("PORT", "8080"))

# ── 工具函数 ──────────────────────────────────────────────────────────
def read_stats():
    try:
        return json.loads(STATS_FILE.read_text())
    except Exception:
        return {"scanned": 0, "hits": 0, "total_running_sec": 0,
                "scan_rate_total_addr_per_sec": 0, "scan_rate_recent_addr_per_sec": 0,
                "keygen_rate_keys_per_sec": 0}

def read_log_lines(n=100):
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception:
        return ["(no log yet)"]

def read_found_lines(n=50):
    try:
        lines = FOUND_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception:
        return []

# ── HTML 页面 ─────────────────────────────────────────────────────────
def render_page():
    stats = read_stats()
    log_lines = read_log_lines(80)
    found_lines = read_found_lines(30)
    log_escaped = "\n".join(log_lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    found_escaped = "\n".join(found_lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scanner Dashboard</title>
<style>
  body {{ font-family: 'SF Mono', Consolas, monospace; background: #0d1117; color: #c9d1d9; margin: 0; padding: 20px; }}
  h1 {{ color: #58a6ff; }}
  h2 {{ color: #8b949e; border-bottom: 1px solid #21262d; padding-bottom: 8px; }}
  .cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px 24px; min-width: 180px; }}
  .card .label {{ color: #8b949e; font-size: 12px; text-transform: uppercase; }}
  .card .value {{ color: #58a6ff; font-size: 24px; font-weight: bold; margin-top: 4px; }}
  pre {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px; overflow-x: auto; font-size: 12px; line-height: 1.5; max-height: 400px; }}
  .hit {{ color: #f0883e; }}
  a {{ color: #58a6ff; }}
</style></head><body>
<h1>Scanner Dashboard</h1>
<div class="cards">
  <div class="card"><div class="label">扫描速度(全程)</div><div class="value">{stats.get('scan_rate_total_addr_per_sec',0)} addr/s</div></div>
  <div class="card"><div class="label">扫描速度(近30)</div><div class="value">{stats.get('scan_rate_recent_addr_per_sec',0)} addr/s</div></div>
  <div class="card"><div class="label">计算速度</div><div class="value">{stats.get('keygen_rate_keys_per_sec',0)} keys/s</div></div>
  <div class="card"><div class="label">累计扫描</div><div class="value">{stats.get('scanned',0)}</div></div>
  <div class="card"><div class="label">命中</div><div class="value hit">{stats.get('hits',0)}</div></div>
  <div class="card"><div class="label">运行时间</div><div class="value">{stats.get('total_running_sec',0)}s</div></div>
</div>
<h2>Scanner Log</h2>
<pre>{log_escaped}</pre>
<h2>Found Wallets</h2>
<pre class="hit">{found_escaped}</pre>
<p style="color:#484f58;margin-top:20px">Auto-refresh every 5s &mdash; <a href="/api/stats">JSON Stats</a> | <a href="/api/log">JSON Log</a> | <a href="/api/found">JSON Found</a></p>
<script>setTimeout(function(){{ location.reload(); }}, 5000);</script>
</body></html>"""

# ── HTTP 处理器 ───────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/stats":
            data = json.dumps(read_stats()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/api/log":
            data = json.dumps({"lines": read_log_lines(200)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/api/found":
            data = json.dumps({"lines": read_found_lines(100)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
        else:
            html = render_page().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)

    def log_message(self, format, *args):
        pass  # silence request logs

# ── 入口 ──────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Viewer listening on http://0.0.0.0:{PORT}/")
    server.serve_forever()

if __name__ == "__main__":
    main()

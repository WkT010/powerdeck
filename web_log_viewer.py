#!/usr/bin/env python3
"""Web 日志查看器：端口 8080，提供实时日志/速度卡片/命中列表。"""

import json
import os
import time
import logging
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# ── 配置 ──────────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path("/workspace/output")
STATS_FILE = OUTPUT_DIR / "stats.json"
FOUND_FILE = OUTPUT_DIR / "found_wallets.jsonl"
SCANNER_LOG = OUTPUT_DIR / "scanner.log"
VIEWER_LOG = OUTPUT_DIR / "viewer.log"
PORT = int(os.environ.get("PORT", "8080"))

# ── 日志 ──────────────────────────────────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(VIEWER_LOG, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("viewer")

# ── 数据读取 ──────────────────────────────────────────────────────────────────
def read_stats():
    try:
        with open(STATS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def read_recent_hits(limit=20):
    hits = []
    try:
        with open(FOUND_FILE) as f:
            lines = f.readlines()
        for line in lines[-limit:]:
            try:
                hits.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                pass
    except FileNotFoundError:
        pass
    return hits

def read_scanner_log(tail=50):
    try:
        with open(SCANNER_LOG) as f:
            lines = f.readlines()
        return "".join(lines[-tail:])
    except FileNotFoundError:
        return "（暂无日志）"

# ── HTML 页面 ─────────────────────────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scanner Dashboard</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system, 'Segoe UI', Roboto, monospace; background:#0d1117; color:#c9d1d9; padding:20px; }}
  h1 {{ color:#58a6ff; margin-bottom:16px; font-size:1.5em; }}
  .cards {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; min-width:180px; }}
  .card .label {{ font-size:12px; color:#8b949e; margin-bottom:4px; }}
  .card .value {{ font-size:24px; font-weight:bold; color:#58a6ff; }}
  .card .unit {{ font-size:14px; color:#8b949e; }}
  .section {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; margin-bottom:16px; }}
  .section h2 {{ color:#58a6ff; margin-bottom:10px; font-size:1.1em; }}
  .log {{ background:#0d1117; border:1px solid #30363d; border-radius:4px; padding:12px; overflow-x:auto; font-size:12px; line-height:1.6; max-height:400px; overflow-y:auto; white-space:pre-wrap; word-break:break-all; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ text-align:left; padding:8px; border-bottom:1px solid #30363d; color:#58a6ff; }}
  td {{ padding:8px; border-bottom:1px solid #21262d; }}
  .hit {{ color:#3fb950; }}
  .refresh {{ color:#8b949e; font-size:12px; }}
</style>
</head>
<body>
<h1>Scanner Dashboard</h1>

<div class="cards">
  <div class="card">
    <div class="label">扫描速度 (全程)</div>
    <div class="value">{scan_rate_total} <span class="unit">addr/s</span></div>
  </div>
  <div class="card">
    <div class="label">扫描速度 (近30s)</div>
    <div class="value">{scan_rate_recent} <span class="unit">addr/s</span></div>
  </div>
  <div class="card">
    <div class="label">计算速度</div>
    <div class="value">{keygen_rate} <span class="unit">keys/s</span></div>
  </div>
  <div class="card">
    <div class="label">累计扫描</div>
    <div class="value">{scanned}</div>
  </div>
  <div class="card">
    <div class="label">命中</div>
    <div class="value hit">{hits}</div>
  </div>
  <div class="card">
    <div class="label">运行时间</div>
    <div class="value">{running_sec}s</div>
  </div>
</div>

<div class="section">
  <h2>命中列表 <span class="refresh">(最近 {hit_limit} 条)</span></h2>
  {hits_table}
</div>

<div class="section">
  <h2>Scanner 日志 <span class="refresh">(最近 50 行)</span></h2>
  <div class="log">{scanner_log_escaped}</div>
</div>

<p class="refresh">自动刷新间隔: 5s | 当前时间: {now}</p>

<script>
setTimeout(function(){{ location.reload(); }}, 5000);
</script>
</body>
</html>"""

def build_page():
    s = read_stats()
    hits_data = read_recent_hits(20)
    scan_log = read_scanner_log(50)

    # 命中表格
    if hits_data:
        rows = ""
        for h in reversed(hits_data):
            addr = h.get("address", "?")
            chains = ", ".join(hit.get("chain","?") for hit in h.get("hits", []))
            ts = h.get("timestamp", "?")
            rows += f"<tr><td>{ts}</td><td>{addr}</td><td>{chains}</td></tr>"
        hits_table = f"<table><tr><th>时间</th><th>地址</th><th>链</th></tr>{rows}</table>"
    else:
        hits_table = "<p style='color:#8b949e'>暂无命中</p>"

    # HTML 转义日志
    import html
    log_escaped = html.escape(scan_log)

    return HTML_TEMPLATE.format(
        scan_rate_total=s.get("scan_rate_total_addr_per_sec", 0),
        scan_rate_recent=s.get("scan_rate_recent_addr_per_sec", 0),
        keygen_rate=s.get("keygen_rate_keys_per_sec", 0),
        scanned=s.get("scanned", 0),
        hits=s.get("hits", 0),
        running_sec=round(s.get("total_running_sec", 0), 1),
        hit_limit=20,
        hits_table=hits_table,
        scanner_log_escaped=log_escaped,
        now=datetime.utcnow().isoformat()+"Z",
    )

# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = build_page()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
        elif self.path == "/api/stats":
            s = read_stats()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(s).encode())
        elif self.path == "/api/hits":
            h = read_recent_hits(50)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(h).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        log.info(f"HTTP {args[0]}")

# ── 启动 ──────────────────────────────────────────────────────────────────────
def main():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    log.info(f"viewer 启动, 端口={PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("viewer 停止")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()

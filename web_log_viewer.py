#!/usr/bin/env python3
"""Web log viewer for scanner stats, hits, and logs."""

import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

OUTPUT_DIR = "/workspace/output"
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
SCANNER_LOG = os.path.join(OUTPUT_DIR, "scanner.log")
VIEWER_LOG = os.path.join(OUTPUT_DIR, "viewer.log")
PORT = int(os.environ.get("PORT", "8080"))


def read_json_safe(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def read_lines_tail(path, n=50):
    try:
        with open(path, "r") as f:
            lines = f.readlines()
            return lines[-n:]
    except FileNotFoundError:
        return []


class ViewerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        msg = f"[{self.log_date_time_string()}] {format % args}"
        with open(VIEWER_LOG, "a") as f:
            f.write(msg + "\n")

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.serve_index()
        elif self.path == "/api/stats":
            self.serve_stats()
        elif self.path == "/api/hits":
            self.serve_hits()
        elif self.path == "/api/logs":
            self.serve_logs()
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_error(404)

    def serve_index(self):
        html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Multi-Chain Scanner Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:SF Mono,Menlo,Consolas,monospace;background:#0d1117;color:#c9d1d9;padding:20px}
.container{max-width:1200px;margin:0 auto}
h1{font-size:24px;margin-bottom:20px;color:#58a6ff}
h2{font-size:16px;margin-bottom:12px;color:#79c0ff;text-transform:uppercase;letter-spacing:1px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
.card .label{font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:1px}
.card .value{font-size:24px;font-weight:700;color:#58a6ff;margin-top:4px}
.card .value.green{color:#3fb950}
.card .value.orange{color:#d29922}
.card .value.red{color:#f85149}
.section{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:16px}
.log-entry{font-size:12px;color:#8b949e;padding:4px 0;border-bottom:1px solid #21262d}
.log-entry:last-child{border-bottom:none}
.hit-entry{font-size:12px;color:#3fb950;padding:4px 0;border-bottom:1px solid #21262d;font-family:monospace;word-break:break-all}
.hit-entry:last-child{border-bottom:none}
.refresh{color:#8b949e;font-size:12px;margin-bottom:16px}
.refresh span{color:#58a6ff}
</style>
</head>
<body>
<div class="container">
<h1>⬡ Multi-Chain Private Key Scanner</h1>
<div class="refresh" id="refresh">自动刷新中... <span id="refresh-time"></span></div>
<h2>📊 Speed Metrics</h2>
<div class="grid" id="stats"></div>
<h2>🎯 Recent Hits</h2>
<div class="section" id="hits"></div>
<h2>📝 Scanner Log</h2>
<div class="section" id="logs"></div>
</div>
<script>
async function refresh(){
  try{
    const [statsRes, hitsRes, logsRes] = await Promise.all([
      fetch('/api/stats'), fetch('/api/hits'), fetch('/api/logs')
    ]);
    const stats = await statsRes.json();
    const hits = await hitsRes.json();
    const logs = await logsRes.json();

    if(stats){
      document.getElementById('stats').innerHTML = `
        <div class="card"><div class="label">扫描速度(全程)</div><div class="value green">${stats.scan_rate_total_addr_per_sec||0} addr/s</div></div>
        <div class="card"><div class="label">扫描速度(近30)</div><div class="value orange">${stats.scan_rate_recent_addr_per_sec||0} addr/s</div></div>
        <div class="card"><div class="label">计算速度</div><div class="value">${stats.keygen_rate_keys_per_sec||0} keys/s</div></div>
        <div class="card"><div class="label">累计扫描</div><div class="value">${stats.scanned||0}</div></div>
        <div class="card"><div class="label">命中数</div><div class="value ${stats.hits>0?'green':'red'}">${stats.hits||0}</div></div>
        <div class="card"><div class="label">运行时长</div><div class="value">${stats.total_running_sec||0}s</div></div>
        <div class="card"><div class="label">链数</div><div class="value">${(stats.chains||[]).length}</div></div>
        <div class="card"><div class="label">Workers</div><div class="value">${stats.workers||0}</div></div>
      `;
    }

    const hitsDiv = document.getElementById('hits');
    if(hits.length > 0){
      hitsDiv.innerHTML = hits.slice(-20).reverse().map(h =>
        `<div class="hit-entry">[${h.timestamp}] ${h.address} → ${Object.keys(h.chains||{}).join(', ')}</div>`
      ).join('');
    } else {
      hitsDiv.innerHTML = '<div style="color:#8b949e;font-size:13px">暂无命中记录</div>';
    }

    const logsDiv = document.getElementById('logs');
    if(logs.length > 0){
      logsDiv.innerHTML = logs.slice(-50).reverse().map(l =>
        `<div class="log-entry">${l}</div>`
      ).join('');
    } else {
      logsDiv.innerHTML = '<div style="color:#8b949e;font-size:13px">暂无日志</div>';
    }

    document.getElementById('refresh-time').textContent = new Date().toLocaleTimeString();
  }catch(e){console.error(e)}
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>"""
        content = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content)

    def serve_stats(self):
        stats = read_json_safe(STATS_FILE) or {}
        body = json.dumps(stats).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def serve_hits(self):
        hits = []
        try:
            with open(FOUND_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            hits.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except FileNotFoundError:
            pass
        body = json.dumps(hits).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def serve_logs(self):
        logs = read_lines_tail(SCANNER_LOG, 200)
        body = json.dumps([l.strip() for l in logs if l.strip()]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(VIEWER_LOG, "a") as f:
        f.write(f"[{__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}] Viewer starting on port {PORT}\n")
    server = HTTPServer(("0.0.0.0", PORT), ViewerHandler)
    print(f"Viewer running on http://0.0.0.0:{PORT}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
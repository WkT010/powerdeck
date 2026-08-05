#!/usr/bin/env python3
import os
import sys
import json
import time
import http.server
import socketserver
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

OUTPUT_DIR = "/workspace/output"
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
SCANNER_LOG = os.path.join(OUTPUT_DIR, "scanner.log")
VIEWER_LOG = os.path.join(OUTPUT_DIR, "viewer.log")
PORT = int(os.environ.get("PORT", "8080"))


def log_msg(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    line = f"[{ts}] {msg}\n"
    with open(VIEWER_LOG, "a") as f:
        f.write(line)


def read_json_file(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def read_tail_lines(path, n=50):
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        return lines[-n:]
    except Exception:
        return []


def read_jsonl_tail(path, n=50):
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        records = []
        for line in lines[-n:]:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
        return records
    except Exception:
        return []


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scanner Monitor</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'SF Mono', 'Monaco', 'Menlo', monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }
  h1 { color: #00ff88; margin-bottom: 20px; font-size: 24px; text-transform: uppercase; letter-spacing: 2px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
  .card { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 15px; }
  .card .label { color: #888; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
  .card .value { color: #00ff88; font-size: 24px; font-weight: bold; margin-top: 5px; }
  .card .value.warn { color: #ffaa00; }
  .card .value.err { color: #ff4444; }
  .section { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 15px; margin-bottom: 20px; }
  .section h2 { color: #00aaff; font-size: 16px; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px; }
  .log-entry { padding: 4px 0; border-bottom: 1px solid #222; font-size: 12px; }
  .log-entry .ts { color: #666; }
  .log-entry .msg { color: #e0e0e0; }
  .hit { color: #ffaa00; }
  .refresh { color: #888; font-size: 12px; margin-top: 10px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { text-align: left; padding: 8px; color: #888; border-bottom: 1px solid #333; }
  td { padding: 6px 8px; border-bottom: 1px solid #222; word-break: break-all; }
  .address { color: #00aaff; }
  .chain { color: #ffaa00; }
  .asset { color: #00ff88; }
  .empty { color: #555; text-align: center; padding: 20px; }
</style>
</head>
<body>
<h1>Multi-Chain Private Key Scanner</h1>
<div class="grid">
  <div class="card">
    <div class="label">扫描速度(全程)</div>
    <div class="value" id="rate-total">--</div>
    <div class="refresh">addr/s</div>
  </div>
  <div class="card">
    <div class="label">扫描速度(近30s)</div>
    <div class="value" id="rate-recent">--</div>
    <div class="refresh">addr/s</div>
  </div>
  <div class="card">
    <div class="label">计算速度</div>
    <div class="value" id="keygen-rate">--</div>
    <div class="refresh">keys/s</div>
  </div>
  <div class="card">
    <div class="label">累计扫描</div>
    <div class="value" id="scanned">--</div>
  </div>
  <div class="card">
    <div class="label">命中数</div>
    <div class="value warn" id="hits">--</div>
  </div>
  <div class="card">
    <div class="label">运行时长</div>
    <div class="value" id="runtime">--</div>
    <div class="refresh">seconds</div>
  </div>
</div>
<div class="section">
  <h2>实时日志</h2>
  <div id="log"></div>
</div>
<div class="section">
  <h2>最新命中</h2>
  <div id="hits-list"></div>
</div>
<script>
async function refresh() {
  try {
    const stats = await fetch('/api/stats').then(r => r.json());
    document.getElementById('rate-total').textContent = stats.scan_rate_total_addr_per_sec || '0';
    document.getElementById('rate-recent').textContent = stats.scan_rate_recent_addr_per_sec || '0';
    document.getElementById('keygen-rate').textContent = stats.keygen_rate_keys_per_sec || '0';
    document.getElementById('scanned').textContent = (stats.scanned || 0).toLocaleString();
    document.getElementById('hits').textContent = stats.hits || 0;
    document.getElementById('runtime').textContent = stats.total_running_sec || 0;
  } catch(e) {}
  try {
    const logs = await fetch('/api/logs').then(r => r.json());
    document.getElementById('log').innerHTML = logs.map(l =>
      `<div class="log-entry"><span class="ts">${l.split(']')[0]}]</span> <span class="msg">${l.split(']').slice(1).join(']')}</span></div>`
    ).join('') || '<div class="empty">暂无日志</div>';
  } catch(e) {}
  try {
    const hits = await fetch('/api/hits').then(r => r.json());
    if (hits.length === 0) {
      document.getElementById('hits-list').innerHTML = '<div class="empty">暂无命中记录</div>';
    } else {
      document.getElementById('hits-list').innerHTML = '<table><tr><th>时间</th><th>地址</th><th>链</th><th>代币</th><th>余额</th></tr>' +
        hits.map(h => {
          const firstHit = h.hits ? h.hits[0] : {};
          return `<tr><td>${h.timestamp ? h.timestamp.split('T')[1].split('.')[0] : '-'}</td>
            <td class="address">${h.address ? h.address.slice(0,10)}...${h.address ? h.address.slice(-6) : ''}</td>
            <td class="chain">${firstHit.chain || '-'}</td>
            <td class="asset">${firstHit.asset || '-'}</td>
            <td>${firstHit.balance || '-'}</td></tr>`;
        }).join('') + '</table>';
    }
  } catch(e) {}
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>"""


class ViewerHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif path == "/api/stats":
            self._serve_json(read_json_file(STATS_FILE))
        elif path == "/api/logs":
            lines = read_tail_lines(SCANNER_LOG, 50)
            self._serve_json(lines)
        elif path == "/api/hits":
            records = read_jsonl_tail(FOUND_FILE, 50)
            self._serve_json(records)
        elif path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format, *args):
        log_msg(f"{self.client_address[0]} - {format % args}")


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True
    request_queue_size = 10


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    open(VIEWER_LOG, "a").close()
    log_msg(f"Viewer starting on port {PORT}")

    with ReusableTCPServer(("0.0.0.0", PORT), ViewerHandler) as httpd:
        log_msg(f"Viewer listening on 0.0.0.0:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            log_msg("Viewer stopped by user")
            httpd.shutdown()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Web log viewer for scanner - real-time logs, speed cards, and hit list."""

import json
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

OUTPUT_DIR = Path("/workspace/output")
STATS_FILE = OUTPUT_DIR / "stats.json"
FOUND_WALLETS = OUTPUT_DIR / "found_wallets.jsonl"
SCANNER_LOG = OUTPUT_DIR / "scanner.log"
VIEWER_LOG = OUTPUT_DIR / "viewer.log"

PORT = int(os.environ.get("PORT", "8080"))
LOG_TAIL_LINES = int(os.environ.get("LOG_TAIL_LINES", "200"))


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    line = f"[{ts}] [viewer] {msg}"
    print(line, flush=True)
    with open(VIEWER_LOG, "a") as f:
        f.write(line + "\n")


def read_stats():
    try:
        if STATS_FILE.exists():
            with open(STATS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def read_log_tail():
    try:
        if SCANNER_LOG.exists():
            with open(SCANNER_LOG, "r") as f:
                lines = f.readlines()
                return lines[-LOG_TAIL_LINES:]
    except Exception:
        pass
    return []


def read_hits():
    hits = []
    try:
        if FOUND_WALLETS.exists():
            with open(FOUND_WALLETS, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            hits.append(json.loads(line))
                        except Exception:
                            pass
    except Exception:
        pass
    return hits[-50:]


HTML_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scanner Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
    background: #0a0a0f;
    color: #e0e0e0;
    min-height: 100vh;
    padding: 20px;
}
.container { max-width: 1400px; margin: 0 auto; }
h1 {
    font-size: 24px;
    margin-bottom: 20px;
    background: linear-gradient(90deg, #00d4ff, #7b2ff7);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 20px; }
.card {
    background: #151520;
    border: 1px solid #252535;
    border-radius: 8px;
    padding: 16px;
}
.card .label { color: #888; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
.card .value { font-size: 24px; font-weight: bold; margin-top: 8px; }
.card .unit { font-size: 12px; color: #666; margin-left: 4px; }
.card.rate .value { color: #00d4ff; }
.card.hits .value { color: #ff6b6b; }
.card.total .value { color: #7b2ff7; }
.card.runtime .value { color: #51cf66; }
.section {
    background: #151520;
    border: 1px solid #252535;
    border-radius: 8px;
    margin-bottom: 20px;
    overflow: hidden;
}
.section-header {
    padding: 12px 16px;
    border-bottom: 1px solid #252535;
    font-size: 14px;
    font-weight: 600;
    color: #aaa;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.refresh-btn {
    background: #252535;
    border: none;
    color: #aaa;
    padding: 4px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
}
.refresh-btn:hover { background: #353545; color: #fff; }
.log-content {
    padding: 12px 16px;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.6;
    max-height: 400px;
    overflow-y: auto;
    color: #b0b0b0;
}
.log-content .hit { color: #51cf66; font-weight: bold; }
.log-content .error { color: #ff6b6b; }
table { width: 100%; border-collapse: collapse; }
th { background: #1a1a2a; padding: 10px; text-align: left; font-size: 12px; color: #888; text-transform: uppercase; }
td { padding: 10px; border-top: 1px solid #252535; font-size: 12px; }
tr:hover { background: #1a1a2a; }
td.addr { font-family: 'Courier New', monospace; color: #00d4ff; word-break: break-all; }
td.bal { color: #51cf66; font-weight: bold; }
td.time { color: #666; }
.empty { padding: 40px; text-align: center; color: #555; }
.hit-assets { color: #888; font-size: 11px; margin-top: 4px; }
.chain-badge {
    display: inline-block;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 10px;
    margin-right: 2px;
    background: #252535;
    color: #aaa;
}
.chain-badge.ethereum { background: #3c3c6b; color: #fff; }
.chain-badge.polygon { background: #8247e5; color: #fff; }
.chain-badge.arbitrum { background: #28a0f0; color: #fff; }
.chain-badge.optimism { background: #ff0420; color: #fff; }
.chain-badge.base { background: #0052ff; color: #fff; }
.chain-badge.linea { background: #00c897; color: #000; }
.chain-badge.scroll { background: #ffe600; color: #000; }
.chain-badge.zksync { background: #8e6bff; color: #fff; }
.chain-badge.mantle { background: #00d4aa; color: #000; }
.chain-badge.blast { background: #ff6b00; color: #fff; }
.auto-refresh { font-size: 11px; color: #555; }
</style>
</head>
<body>
<div class="container">
    <h1>🔍 Multi-Chain Private Key Scanner Dashboard</h1>
    <div class="cards">
        <div class="card rate">
            <div class="label">Scan Rate (Total)</div>
            <div class="value" id="scan-rate-total">0<span class="unit">addr/s</span></div>
        </div>
        <div class="card rate">
            <div class="label">Scan Rate (Recent 30s)</div>
            <div class="value" id="scan-rate-recent">0<span class="unit">addr/s</span></div>
        </div>
        <div class="card rate">
            <div class="label">Key Gen Rate</div>
            <div class="value" id="keygen-rate">0<span class="unit">keys/s</span></div>
        </div>
        <div class="card total">
            <div class="label">Total Scanned</div>
            <div class="value" id="total-scanned">0</div>
        </div>
        <div class="card hits">
            <div class="label">Hits Found</div>
            <div class="value" id="total-hits">0</div>
        </div>
        <div class="card runtime">
            <div class="label">Runtime</div>
            <div class="value" id="runtime">0<span class="unit">s</span></div>
        </div>
    </div>
    <div class="section">
        <div class="section-header">
            <span>📜 Real-time Logs</span>
            <div>
                <span class="auto-refresh" id="log-time"></span>
                <button class="refresh-btn" onclick="refreshLogs()">Refresh</button>
            </div>
        </div>
        <div class="log-content" id="log-content">Loading...</div>
    </div>
    <div class="section">
        <div class="section-header">
            <span>🎯 Hit Wallets (Last 50)</span>
            <button class="refresh-btn" onclick="refreshHits()">Refresh</button>
        </div>
        <div id="hits-content">Loading...</div>
    </div>
</div>
<script>
async function refreshData() {
    try {
        const statsResp = await fetch('/api/stats');
        const stats = await statsResp.json();
        document.getElementById('scan-rate-total').innerHTML = (stats.scan_rate_total_addr_per_sec || 0) + '<span class="unit">addr/s</span>';
        document.getElementById('scan-rate-recent').innerHTML = (stats.scan_rate_recent_addr_per_sec || 0) + '<span class="unit">addr/s</span>';
        document.getElementById('keygen-rate').innerHTML = (stats.keygen_rate_keys_per_sec || 0) + '<span class="unit">keys/s</span>';
        document.getElementById('total-scanned').textContent = stats.scanned || 0;
        document.getElementById('total-hits').textContent = stats.hits || 0;
        document.getElementById('runtime').innerHTML = (stats.total_running_sec || 0) + '<span class="unit">s</span>';
    } catch(e) { console.error(e); }
}
async function refreshLogs() {
    try {
        const resp = await fetch('/api/logs');
        const logs = await resp.json();
        const el = document.getElementById('log-content');
        el.innerHTML = logs.map(l => {
            const cls = l.includes('HIT') ? 'hit' : (l.includes('Error') || l.includes('error') ? 'error' : '');
            return '<div class="' + cls + '">' + escapeHtml(l) + '</div>';
        }).join('');
        document.getElementById('log-time').textContent = 'Updated: ' + new Date().toLocaleTimeString();
        el.scrollTop = el.scrollHeight;
    } catch(e) { console.error(e); }
}
async function refreshHits() {
    try {
        const resp = await fetch('/api/hits');
        const hits = await resp.json();
        const el = document.getElementById('hits-content');
        if (!hits || hits.length === 0) {
            el.innerHTML = '<div class="empty">No hits yet... scanning millions of keys</div>';
            return;
        }
        let html = '<table><thead><tr><th>Time</th><th>Address</th><th>Assets</th></tr></thead><tbody>';
        for (const h of hits) {
            let assetsHtml = '';
            if (h.balances) {
                for (const [key, val] of Object.entries(h.balances)) {
                    const parts = key.split('/');
                    const chain = parts[0] || '';
                    const asset = parts[1] || parts[0] || '';
                    assetsHtml += '<span class="chain-badge ' + chain + '">' + chain + '</span>' + asset + ': ' + val.balance + '<br>';
                }
            }
            html += '<tr><td class="time">' + escapeHtml(h.timestamp || '') + '</td><td class="addr">' + escapeHtml(h.address || '') + '</td><td>' + assetsHtml + '</td></tr>';
        }
        html += '</tbody></table>';
        el.innerHTML = html;
    } catch(e) { console.error(e); }
}
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
function refreshAll() {
    refreshData();
    refreshLogs();
    refreshHits();
}
refreshAll();
setInterval(refreshAll, 3000);
</script>
</body>
</html>
"""


class ViewerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/api/stats":
            self._serve_json(read_stats())
        elif path == "/api/logs":
            self._serve_json(read_log_tail())
        elif path == "/api/hits":
            self._serve_json(read_hits())
        elif path == "/health":
            self._serve_json({"status": "ok"})
        else:
            self.send_error(404, "Not Found")

    def _serve_html(self):
        content = HTML_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_json(self, data):
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server = HTTPServer(("0.0.0.0", PORT), ViewerHandler)
    log(f"Viewer started on port {PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log("Viewer stopped")


if __name__ == "__main__":
    main()

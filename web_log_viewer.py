#!/usr/bin/env python3
"""
Web log viewer for scanner. Runs on port 8080.
Provides real-time logs, speed cards, and hit list.
"""

import os
import sys
import json
import time
import glob
from flask import Flask, jsonify, render_template_string, Response

app = Flask(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
SCANNER_LOG = os.path.join(OUTPUT_DIR, "scanner.log")
VIEWER_LOG = os.path.join(OUTPUT_DIR, "viewer.log")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scanner Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
         background: #0d1117; color: #c9d1d9; padding: 20px; }
  h1 { color: #58a6ff; margin-bottom: 20px; font-size: 1.5em; }
  h2 { color: #7ee787; margin: 20px 0 10px; font-size: 1.1em; border-bottom: 1px solid #30363d; padding-bottom: 8px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
  .card .label { color: #8b949e; font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.5px; }
  .card .value { font-size: 1.8em; font-weight: bold; color: #58a6ff; margin-top: 4px; }
  .card .value.green { color: #7ee787; }
  .card .value.orange { color: #d29922; }
  .card .value.red { color: #f85149; }
  .log-viewer { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px;
                max-height: 400px; overflow-y: auto; font-family: 'SFMono-Regular', monospace;
                font-size: 0.85em; line-height: 1.6; }
  .log-viewer .log-line { border-bottom: 1px solid #21262d; padding: 2px 0; }
  .log-viewer .log-line.hit { color: #7ee787; font-weight: bold; }
  .log-viewer .log-line.error { color: #f85149; }
  table { width: 100%; border-collapse: collapse; margin-top: 10px; background: #161b22;
          border-radius: 8px; overflow: hidden; }
  th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #30363d; font-size: 0.9em; }
  th { background: #21262d; color: #8b949e; text-transform: uppercase; font-size: 0.75em; letter-spacing: 0.5px; }
  tr:hover { background: #1c2128; }
  .hit-badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
               font-size: 0.75em; font-weight: bold; }
  .hit-badge.eth { background: #627eea33; color: #627eea; }
  .hit-badge.polygon { background: #8247e533; color: #8247e5; }
  .hit-badge.arbitrum { background: #28a0f033; color: #28a0f0; }
  .hit-badge.optimism { background: #ff042033; color: #ff0420; }
  .hit-badge.base { background: #0052ff33; color: #0052ff; }
  .hit-badge.linea { background: #12121233; color: #8b949e; }
  .hit-badge.scroll { background: #ffeeda33; color: #d29922; }
  .hit-badge.zksync { background: #8e7dff33; color: #8e7dff; }
  .hit-badge.mantle { background: #14b8a633; color: #14b8a6; }
  .hit-badge.blast { background: #ffcc0033; color: #d29922; }
  .refresh-info { text-align: center; color: #8b949e; font-size: 0.8em; margin-top: 16px; }
  .empty { color: #484f58; font-style: italic; padding: 20px; text-align: center; }
</style>
</head>
<body>
<h1>🔍 Multi-Chain Private Key Scanner Dashboard</h1>
<div class="cards">
  <div class="card">
    <div class="label">扫描速度(全程)</div>
    <div class="value" id="rate-total">-</div>
    <div style="font-size:0.7em;color:#8b949e">addr/s</div>
  </div>
  <div class="card">
    <div class="label">扫描速度(近30s)</div>
    <div class="value green" id="rate-recent">-</div>
    <div style="font-size:0.7em;color:#8b949e">addr/s</div>
  </div>
  <div class="card">
    <div class="label">计算速度</div>
    <div class="value orange" id="rate-keygen">-</div>
    <div style="font-size:0.7em;color:#8b949e">keys/s</div>
  </div>
  <div class="card">
    <div class="label">累计扫描</div>
    <div class="value" id="total-scanned">-</div>
  </div>
  <div class="card">
    <div class="label">命中钱包</div>
    <div class="value green" id="total-hits">-</div>
  </div>
  <div class="card">
    <div class="label">运行时长</div>
    <div class="value" id="uptime">-</div>
    <div style="font-size:0.7em;color:#8b949e">seconds</div>
  </div>
</div>

<h2>📋 Recent Logs</h2>
<div class="log-viewer" id="log-viewer">Loading...</div>

<h2>🎯 Hit Wallets</h2>
<div id="hits-container">Loading...</div>

<div class="refresh-info">Auto-refreshing every 3 seconds · Updated: <span id="update-time">-</span></div>

<script>
async function refresh() {
  try {
    const stats = await fetch('/api/stats').then(r => r.json());
    document.getElementById('rate-total').textContent = stats.scan_rate_total_addr_per_sec || 0;
    document.getElementById('rate-recent').textContent = stats.scan_rate_recent_addr_per_sec || 0;
    document.getElementById('rate-keygen').textContent = stats.keygen_rate_keys_per_sec || 0;
    document.getElementById('total-scanned').textContent = (stats.scanned || 0).toLocaleString();
    document.getElementById('total-hits').textContent = (stats.hits || 0).toLocaleString();
    document.getElementById('uptime').textContent = (stats.total_running_sec || 0).toLocaleString();
    document.getElementById('update-time').textContent = new Date().toLocaleTimeString();

    const logs = await fetch('/api/logs').then(r => r.json());
    const viewer = document.getElementById('log-viewer');
    if (logs.length === 0) {
      viewer.innerHTML = '<div class="empty">No logs yet...</div>';
    } else {
      viewer.innerHTML = logs.map(l => {
        const cls = l.includes('HIT') ? 'hit' : (l.includes('ERROR') ? 'error' : '');
        return `<div class="log-line ${cls}">${l}</div>`;
      }).join('');
      viewer.scrollTop = viewer.scrollHeight;
    }

    const hits = await fetch('/api/hits').then(r => r.json());
    const hc = document.getElementById('hits-container');
    if (hits.length === 0) {
      hc.innerHTML = '<div class="empty">No hits yet. Keep scanning!</div>';
    } else {
      hc.innerHTML = '<table><thead><tr><th>Time</th><th>Address</th><th>Chain</th><th>Token</th><th>Balance</th></tr></thead><tbody>' +
        hits.map(h => {
          const chain = h.hits[0]?.chain || 'unknown';
          const chainClass = chain.toLowerCase().replace('-', '');
          const hitList = h.hits.map(hh =>
            `<span class="hit-badge ${chainClass}">${hh.chain}: ${hh.token}</span>`
          ).join(' ');
          const balances = h.hits.map(hh => hh.balance.toLocaleString()).join(', ');
          return `<tr>
            <td>${h.timestamp?.substring(11, 19) || '-'}</td>
            <td style="font-family:monospace;font-size:0.8em">${h.address?.substring(0,10)}...${h.address?.substring(34)}</td>
            <td>${hitList}</td>
            <td>${balances}</td>
          </tr>`;
        }).join('') + '</tbody></table>';
    }
  } catch(e) { console.error(e); }
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""


def read_file_tail(filepath, max_lines=50):
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return [l.rstrip("\n") for l in lines[-max_lines:]]
    except Exception:
        pass
    return []


def read_jsonl_tail(filepath, max_lines=20):
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            records = []
            for line in lines[-max_lines:]:
                try:
                    records.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    pass
            return records
    except Exception:
        pass
    return []


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/stats")
def api_stats():
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
    except Exception:
        pass
    return jsonify({
        "scan_rate_total_addr_per_sec": 0,
        "scan_rate_recent_addr_per_sec": 0,
        "keygen_rate_keys_per_sec": 0,
        "scanned": 0,
        "hits": 0,
        "total_running_sec": 0,
    })


@app.route("/api/logs")
def api_logs():
    lines = read_file_tail(SCANNER_LOG, max_lines=50)
    return jsonify(lines)


@app.route("/api/hits")
def api_hits():
    records = read_jsonl_tail(FOUND_FILE, max_lines=20)
    return jsonify(records)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": time.time()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Web viewer starting on {host}:{port}")
    app.run(host=host, port=port, debug=False)

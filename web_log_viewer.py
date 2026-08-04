#!/usr/bin/env python3
"""
Web log viewer for the scanner.
Serves real-time logs, speed cards, and hit list on port 8080.
"""

import os
import json
import time
from flask import Flask, jsonify, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
SCANNER_LOG = os.path.join(OUTPUT_DIR, "scanner.log")
VIEWER_LOG = os.path.join(OUTPUT_DIR, "viewer.log")

app = Flask(__name__)


def read_file_tail(path, lines=50):
    try:
        with open(path, "r") as f:
            all_lines = f.readlines()
            return all_lines[-lines:]
    except Exception:
        return []


def read_json_file(path):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def read_found_wallets(limit=100):
    try:
        if os.path.exists(FOUND_FILE):
            with open(FOUND_FILE, "r") as f:
                lines = f.readlines()
                records = []
                for line in lines[-limit:]:
                    try:
                        records.append(json.loads(line.strip()))
                    except Exception:
                        pass
                return records
    except Exception:
        pass
    return []


@app.route("/")
def index():
    return HTML_PAGE


@app.route("/api/stats")
def api_stats():
    return jsonify(read_json_file(STATS_FILE))


@app.route("/api/logs")
def api_logs():
    lines = read_file_tail(SCANNER_LOG, lines=100)
    return jsonify({"logs": [l.rstrip("\n") for l in lines]})


@app.route("/api/hits")
def api_hits():
    return jsonify({"hits": read_found_wallets(limit=200)})


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "timestamp": time.time()})


HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Multi-Chain Scanner Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0e1a; color: #e0e0e0; padding: 20px; }
.container { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 1.5em; margin-bottom: 20px; color: #4fc3f7; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px; }
.card { background: #1a1f2e; border-radius: 8px; padding: 20px; border-left: 4px solid #4fc3f7; }
.card .label { font-size: 0.85em; color: #888; text-transform: uppercase; letter-spacing: 1px; }
.card .value { font-size: 1.8em; font-weight: bold; color: #4fc3f7; margin-top: 8px; }
.card .unit { font-size: 0.7em; color: #666; margin-left: 4px; }
.section { background: #1a1f2e; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
.section h2 { font-size: 1.1em; margin-bottom: 15px; color: #4fc3f7; border-bottom: 1px solid #2a3040; padding-bottom: 8px; }
.log-container { max-height: 400px; overflow-y: auto; font-family: 'Monaco', 'Consolas', monospace; font-size: 0.8em; line-height: 1.6; background: #0d1117; border-radius: 4px; padding: 15px; }
.log-container .log-line { padding: 2px 0; border-bottom: 1px solid #1a1f2e; }
.log-container .log-line.hit { color: #ff9800; font-weight: bold; }
.hit-list { max-height: 300px; overflow-y: auto; }
.hit-item { background: #0d1117; border-radius: 4px; padding: 10px; margin-bottom: 8px; font-family: 'Monaco', 'Consolas', monospace; font-size: 0.75em; word-break: break-all; }
.hit-item .addr { color: #4fc3f7; }
.hit-item .balances { color: #ff9800; margin-top: 5px; }
.auto-refresh { display: flex; align-items: center; gap: 10px; margin-bottom: 15px; font-size: 0.85em; color: #888; }
.auto-refresh input { width: 40px; padding: 4px; background: #0d1117; border: 1px solid #2a3040; color: #e0e0e0; border-radius: 4px; text-align: center; }
.refresh-btn { background: #4fc3f7; color: #0a0e1a; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-weight: bold; }
.refresh-btn:hover { background: #29b6f6; }
</style>
</head>
<body>
<div class="container">
  <h1>🔍 Multi-Chain Private Key Scanner</h1>
  <div class="auto-refresh">
    <label>Auto-refresh (sec):</label>
    <input type="number" id="interval" value="5" min="1" max="60">
    <button class="refresh-btn" onclick="refreshAll()">🔄 Refresh Now</button>
  </div>
  <div class="cards" id="cards"></div>
  <div class="section">
    <h2>📋 Live Logs</h2>
    <div class="log-container" id="logs">Loading...</div>
  </div>
  <div class="section">
    <h2>🎯 Hit Wallets</h2>
    <div class="hit-list" id="hits">Loading...</div>
  </div>
</div>
<script>
async function refreshAll() {
  try {
    const [statsRes, logsRes, hitsRes] = await Promise.all([
      fetch('/api/stats'),
      fetch('/api/logs'),
      fetch('/api/hits')
    ]);
    const stats = await statsRes.json();
    const logs = await logsRes.json();
    const hits = await hitsRes.json();

    const cardsDiv = document.getElementById('cards');
    const items = [
      { label: '扫描速度(全程)', value: stats.scan_rate_total_addr_per_sec || 0, unit: 'addr/s' },
      { label: '扫描速度(近30)', value: stats.scan_rate_recent_addr_per_sec || 0, unit: 'addr/s' },
      { label: '计算速度', value: stats.keygen_rate_keys_per_sec || 0, unit: 'keys/s' },
      { label: '累计扫描', value: stats.scanned || 0, unit: '' },
      { label: '命中', value: stats.hits || 0, unit: '' },
      { label: '本次运行', value: stats.total_running_sec || 0, unit: 's' },
    ];
    cardsDiv.innerHTML = items.map(c =>
      `<div class="card"><div class="label">${c.label}</div><div class="value">${typeof c.value === 'number' ? c.value.toLocaleString(undefined, {maximumFractionDigits: 2}) : c.value}<span class="unit">${c.unit}</span></div></div>`
    ).join('');

    const logsDiv = document.getElementById('logs');
    logsDiv.innerHTML = (logs.logs || []).map(l =>
      `<div class="log-line ${l.includes('HIT') ? 'hit' : ''}">${escapeHtml(l)}</div>`
    ).join('') || '<div class="log-line" style="color:#666">No logs yet...</div>';
    logsDiv.scrollTop = logsDiv.scrollHeight;

    const hitsDiv = document.getElementById('hits');
    hitsDiv.innerHTML = (hits.hits || []).slice(-20).reverse().map(h =>
      `<div class="hit-item"><div class="addr">${h.address}</div><div class="balances">${JSON.stringify(h.balances)}</div></div>`
    ).join('') || '<div style="color:#666; font-size:0.9em; padding:10px;">No hits yet...</div>';
  } catch(e) {
    console.error(e);
  }
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

setInterval(refreshAll, parseInt(document.getElementById('interval').value) * 1000 || 5000);
refreshAll();
</script>
</body>
</html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    log_msg = f"Viewer starting on port {port} at {time.strftime('%Y-%m-%d %H:%M:%S')}"
    try:
        with open(VIEWER_LOG, "a") as f:
            f.write(f"[{log_msg}]\n")
    except Exception:
        pass
    print(log_msg, flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

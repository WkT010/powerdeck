#!/usr/bin/env python3
"""
Web log viewer for the multi-chain private key scanner.
Serves real-time logs, speed cards, and hit list on port 8080.
"""

import os
import json
import time
from flask import Flask, jsonify, render_template_string, Response

app = Flask(__name__)

OUTPUT_DIR = "/workspace/output"
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
SCANNER_LOG = os.path.join(OUTPUT_DIR, "scanner.log")

INDEX_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scanner Monitor</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0d1117; color: #c9d1d9; padding: 20px;
  }
  h1 { font-size: 24px; margin-bottom: 20px; color: #58a6ff; }
  .container { max-width: 1200px; margin: 0 auto; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card {
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 16px;
  }
  .card .label { font-size: 12px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; }
  .card .value { font-size: 28px; font-weight: 700; margin-top: 8px; color: #58a6ff; }
  .card .unit { font-size: 14px; color: #8b949e; margin-left: 4px; }
  .section { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
  .section h2 { font-size: 16px; color: #58a6ff; margin-bottom: 12px; }
  .log-box {
    background: #0d1117; border-radius: 4px; padding: 12px;
    font-family: 'Courier New', monospace; font-size: 12px;
    max-height: 400px; overflow-y: auto; white-space: pre-wrap;
  }
  .hit-list { max-height: 300px; overflow-y: auto; }
  .hit-item { padding: 8px; border-bottom: 1px solid #30363d; font-size: 12px; }
  .hit-item:last-child { border-bottom: none; }
  .hit-item .addr { color: #3fb950; font-family: monospace; }
  .hit-item .chains { color: #d29922; margin-left: 8px; }
  .timestamp { color: #8b949e; font-size: 11px; }
  .refresh-info { font-size: 12px; color: #8b949e; text-align: right; margin-top: 8px; }
</style>
</head>
<body>
<div class="container">
  <h1>🔍 Multi-Chain Scanner Monitor</h1>
  <div class="cards">
    <div class="card">
      <div class="label">扫描速度 (全程)</div>
      <div class="value" id="scan-total">-- <span class="unit">addr/s</span></div>
    </div>
    <div class="card">
      <div class="label">扫描速度 (近30s)</div>
      <div class="value" id="scan-recent">-- <span class="unit">addr/s</span></div>
    </div>
    <div class="card">
      <div class="label">计算速度</div>
      <div class="value" id="keygen-rate">-- <span class="unit">keys/s</span></div>
    </div>
    <div class="card">
      <div class="label">累计扫描</div>
      <div class="value" id="scanned">--</div>
    </div>
    <div class="card">
      <div class="label">命中</div>
      <div class="value" id="hits" style="color:#3fb950">--</div>
    </div>
    <div class="card">
      <div class="label">运行时间</div>
      <div class="value" id="uptime">-- <span class="unit">s</span></div>
    </div>
  </div>
  <div class="section">
    <h2>📋 最近日志</h2>
    <div class="log-box" id="log-box">加载中...</div>
  </div>
  <div class="section">
    <h2>🎯 命中列表</h2>
    <div class="hit-list" id="hit-list">加载中...</div>
  </div>
  <div class="refresh-info" id="refresh-info"></div>
</div>
<script>
async function refresh() {
  try {
    const [statsRes, logRes, hitsRes] = await Promise.all([
      fetch('/api/stats'),
      fetch('/api/log'),
      fetch('/api/hits'),
    ]);
    const stats = await statsRes.json();
    document.getElementById('scan-total').innerHTML = (stats.scan_rate_total_addr_per_sec || 0).toFixed(1) + ' <span class="unit">addr/s</span>';
    document.getElementById('scan-recent').innerHTML = (stats.scan_rate_recent_addr_per_sec || 0).toFixed(1) + ' <span class="unit">addr/s</span>';
    document.getElementById('keygen-rate').innerHTML = (stats.keygen_rate_keys_per_sec || 0).toFixed(1) + ' <span class="unit">keys/s</span>';
    document.getElementById('scanned').textContent = stats.scanned || 0;
    document.getElementById('hits').textContent = stats.hits || 0;
    document.getElementById('uptime').innerHTML = (stats.total_running_sec || 0) + ' <span class="unit">s</span>';
    document.getElementById('refresh-info').textContent = '更新: ' + new Date().toLocaleTimeString();
  } catch(e) {}

  try {
    const logText = await logRes.text();
    document.getElementById('log-box').textContent = logText || '无日志';
  } catch(e) {}

  try {
    const hits = await hitsRes.json();
    const html = hits.length === 0
      ? '<div style="color:#8b949e;padding:8px">暂无命中记录</div>'
      : hits.map(h => `
          <div class="hit-item">
            <span class="timestamp">${h.timestamp || ''}</span>
            <span class="addr">${h.address || ''}</span>
            <span class="chains">命中链: ${Object.keys(h.findings || {}).join(', ')}</span>
          </div>
        `).join('');
    document.getElementById('hit-list').innerHTML = html;
  } catch(e) {}
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/api/stats")
def api_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                return jsonify(json.load(f))
        except Exception:
            pass
    return jsonify({
        "scanned": 0,
        "hits": 0,
        "total_running_sec": 0,
        "scan_rate_total_addr_per_sec": 0,
        "scan_rate_recent_addr_per_sec": 0,
        "keygen_rate_keys_per_sec": 0,
    })


@app.route("/api/log")
def api_log():
    if os.path.exists(SCANNER_LOG):
        try:
            with open(SCANNER_LOG, "r") as f:
                lines = f.readlines()
            return "".join(lines[-100:])
        except Exception:
            pass
    return "日志文件不存在"


@app.route("/api/hits")
def api_hits():
    if os.path.exists(FOUND_FILE):
        try:
            hits = []
            with open(FOUND_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            hits.append(json.loads(line))
                        except Exception:
                            pass
            return jsonify(hits[-50:])
        except Exception:
            pass
    return jsonify([])


def main():
    port = int(os.environ.get("PORT", "8080"))
    log_msg = f"Viewer starting on port {port}..."
    print(log_msg)
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()

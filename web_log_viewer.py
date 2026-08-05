#!/usr/bin/env python3
"""Web log viewer: real-time stats, hit list, and logs from the scanner."""

import json
import os
import time
from flask import Flask, jsonify, render_template_string

OUTPUT_DIR = "/workspace/output"
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
LOG_FILE = os.path.join(OUTPUT_DIR, "scanner.log")

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scanner Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0a0e1a; color: #e0e6ed; min-height: 100vh; padding: 20px;
  }
  .container { max-width: 1200px; margin: 0 auto; }
  h1 { font-size: 1.4em; margin-bottom: 20px; color: #58a6ff; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card {
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 16px; transition: border-color 0.2s;
  }
  .card:hover { border-color: #58a6ff; }
  .card .label { font-size: 0.8em; color: #8b949e; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
  .card .value { font-size: 1.6em; font-weight: 600; color: #58a6ff; }
  .card .value.success { color: #3fb950; }
  .card .value.warn { color: #d29922; }
  .section { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
  .section h2 { font-size: 1em; margin-bottom: 12px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
  th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #21262d; }
  th { color: #8b949e; font-weight: 500; }
  tr:hover { background: #1c2128; }
  .log-line { font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace; font-size: 0.8em; padding: 4px 8px; border-bottom: 1px solid #21262d; }
  .log-line:last-child { border-bottom: none; }
  .addr { font-family: 'SF Mono', Monaco, monospace; color: #a5d6ff; word-break: break-all; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: 500; }
  .badge-hit { background: #1f6feb33; color: #58a6ff; }
  .empty { color: #484f58; font-style: italic; text-align: center; padding: 20px; }
  .refresh-time { font-size: 0.75em; color: #484f58; margin-top: 8px; }
</style>
</head>
<body>
<div class="container">
  <h1>🔍 Multi-Chain Scanner Dashboard</h1>
  <div class="grid">
    <div class="card">
      <div class="label">扫描速度 (全程)</div>
      <div class="value">{{ stats.scan_rate_total_addr_per_sec|default(0) }} addr/s</div>
    </div>
    <div class="card">
      <div class="label">扫描速度 (近30s)</div>
      <div class="value">{{ stats.scan_rate_recent_addr_per_sec|default(0) }} addr/s</div>
    </div>
    <div class="card">
      <div class="label">计算速度</div>
      <div class="value">{{ stats.keygen_rate_keys_per_sec|default(0) }} keys/s</div>
    </div>
    <div class="card">
      <div class="label">累计扫描</div>
      <div class="value success">{{ stats.scanned|default(0) }}</div>
    </div>
    <div class="card">
      <div class="label">命中数</div>
      <div class="value success">{{ stats.hits|default(0) }}</div>
    </div>
    <div class="card">
      <div class="label">运行时间</div>
      <div class="value">{{ stats.total_running_sec|default(0) }}s</div>
    </div>
  </div>

  <div class="section">
    <h2>🎯 命中地址 (最近 50 条)</h2>
    {% if hits %}
    <table>
      <thead>
        <tr><th>地址</th><th>原生链</th><th>ERC20 链</th><th>时间</th></tr>
      </thead>
      <tbody>
        {% for hit in hits %}
        <tr>
          <td class="addr">{{ hit.address }}</td>
          <td>
            {% for chain in hit.native_chains %}
              <span class="badge badge-hit">{{ chain }}</span>
            {% endfor %}
          </td>
          <td>
            {% for chain in hit.erc20_chains %}
              <span class="badge badge-hit">{{ chain }}</span>
            {% endfor %}
          </td>
          <td style="white-space:nowrap;color:#8b949e;">{{ hit.timestamp[:19] if hit.timestamp else '' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="empty">暂无命中记录</p>
    {% endif %}
  </div>

  <div class="section">
    <h2>📋 最近日志 (最后 30 行)</h2>
    {% if logs %}
      {% for line in logs %}
      <div class="log-line">{{ line }}</div>
      {% endfor %}
    {% else %}
    <p class="empty">暂无日志</p>
    {% endif %}
  </div>

  <p class="refresh-time">数据更新时间: {{ stats.timestamp|default('N/A') }}</p>
</div>
<script>
  setTimeout(function(){ location.reload(); }, 5000);
</script>
</body>
</html>
"""


def read_json_file(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def read_hits(limit=50):
    hits = []
    try:
        if not os.path.exists(FOUND_FILE):
            return hits
        with open(FOUND_FILE, "r") as f:
            lines = f.readlines()
        for line in lines[-limit:]:
            try:
                entry = json.loads(line.strip())
                hits.append({
                    "address": entry.get("address", ""),
                    "native_chains": list(entry.get("native_balances", {}).keys()),
                    "erc20_chains": list(entry.get("erc20_balances", {}).keys()),
                    "timestamp": entry.get("timestamp", ""),
                })
            except Exception:
                continue
    except Exception:
        pass
    return list(reversed(hits))


def read_logs(limit=30):
    try:
        if not os.path.exists(LOG_FILE):
            return []
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
        return [line.rstrip("\n") for line in lines[-limit:]]
    except Exception:
        return []


@app.route("/")
def index():
    stats = read_json_file(STATS_FILE)
    hits = read_hits(50)
    logs = read_logs(30)
    return render_template_string(HTML_TEMPLATE, stats=stats, hits=hits, logs=logs)


@app.route("/api/stats")
def api_stats():
    return jsonify(read_json_file(STATS_FILE))


@app.route("/api/hits")
def api_hits():
    return jsonify(read_hits(100))


@app.route("/api/logs")
def api_logs():
    return jsonify(read_logs(100))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)

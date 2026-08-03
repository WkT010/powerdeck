#!/usr/bin/env python3
import os
import json
import time
import glob
from flask import Flask, jsonify, render_template_string, send_from_directory

app = Flask(__name__)

OUTPUT_DIR = "/workspace/output"
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
LOG_FILE = os.path.join(OUTPUT_DIR, "scanner.log")
VIEWER_LOG = os.path.join(OUTPUT_DIR, "viewer.log")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Scanner Dashboard</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body { font-family: 'Segoe UI', Arial, sans-serif; background: #1a1a2e; color: #e0e0e0; margin: 0; padding: 20px; }
        h1 { color: #00d4ff; border-bottom: 2px solid #00d4ff; padding-bottom: 10px; }
        h2 { color: #ff6b6b; margin-top: 30px; }
        .card { background: #16213e; border-radius: 8px; padding: 20px; margin: 10px 0; border-left: 4px solid #0f3460; }
        .card-speed { border-left-color: #00d4ff; }
        .card-info { border-left-color: #53d769; }
        .stat-value { font-size: 28px; font-weight: bold; color: #00d4ff; }
        .stat-label { font-size: 14px; color: #888; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th { background: #0f3460; color: #fff; padding: 10px; text-align: left; }
        td { padding: 8px 10px; border-bottom: 1px solid #333; font-family: monospace; font-size: 12px; }
        tr:hover { background: #16213e; }
        .log-container { background: #0a0a1a; padding: 15px; border-radius: 8px; max-height: 400px; overflow-y: auto; font-family: monospace; font-size: 12px; }
        .log-line { padding: 2px 0; }
        .log-info { color: #53d769; }
        .log-hit { color: #ffd700; font-weight: bold; }
        .log-error { color: #ff6b6b; }
        .status-ok { color: #53d769; }
        .status-err { color: #ff6b6b; }
    </style>
</head>
<body>
    <h1>&#x1F50D; Multi-Chain Private Key Scanner</h1>
    
    <h2>&#x26A1; Speed Metrics</h2>
    <div class="grid">
        <div class="card card-speed">
            <div class="stat-label">Scan Speed (Total)</div>
            <div class="stat-value">{{ stats.scan_rate_total_addr_per_sec }} addr/s</div>
        </div>
        <div class="card card-speed">
            <div class="stat-label">Scan Speed (Recent 30s)</div>
            <div class="stat-value">{{ stats.scan_rate_recent_addr_per_sec }} addr/s</div>
        </div>
        <div class="card card-speed">
            <div class="stat-label">Keygen Speed</div>
            <div class="stat-value">{{ stats.keygen_rate_keys_per_sec }} keys/s</div>
        </div>
    </div>
    
    <h2>&#x1F4CA; Statistics</h2>
    <div class="grid">
        <div class="card card-info">
            <div class="stat-label">Total Scanned</div>
            <div class="stat-value">{{ stats.scanned }}</div>
        </div>
        <div class="card card-info">
            <div class="stat-label">Hits Found</div>
            <div class="stat-value">{{ stats.hits }}</div>
        </div>
        <div class="card card-info">
            <div class="stat-label">Runtime</div>
            <div class="stat-value">{{ stats.total_running_sec }}s</div>
        </div>
    </div>
    
    <h2>&#x1F3AF; Recent Hits</h2>
    {% if hits %}
    <table>
        <tr><th>Time</th><th>Address</th><th>Chains</th><th>ERC20</th></tr>
        {% for hit in hits[:20] %}
        <tr>
            <td>{{ hit.time_str }}</td>
            <td><code>{{ hit.address }}</code></td>
            <td>{{ hit.chain_count }}</td>
            <td>{{ hit.erc20_count }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <div class="card">No hits yet.</div>
    {% endif %}
    
    <h2>&#x1F4DC; Recent Logs</h2>
    <div class="log-container">
        {% for line in logs %}
        <div class="log-line {% if 'HIT' in line %}log-hit{% elif 'ERROR' in line %}log-error{% else %}log-info{% endif %}">{{ line }}</div>
        {% endfor %}
    </div>
    
    <p style="text-align:center; color:#666; margin-top: 30px;">
        Auto-refreshing every 5 seconds &middot; <a href="/api/stats" style="color:#00d4ff">API</a>
    </p>
</body>
</html>
"""


def read_stats():
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "scan_rate_total_addr_per_sec": 0,
            "scan_rate_recent_addr_per_sec": 0,
            "keygen_rate_keys_per_sec": 0,
            "scanned": 0,
            "hits": 0,
            "total_running_sec": 0,
        }


def read_logs(n=50):
    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
        return [l.strip() for l in lines[-n:]]
    except Exception:
        return ["No scanner log available."]


def read_hits(n=20):
    hits = []
    try:
        with open(FOUND_FILE, "r") as f:
            lines = f.readlines()
        for line in reversed(lines[-n * 3 :]):
            try:
                entry = json.loads(line.strip())
                chain_count = len(entry.get("chain_balances", []))
                erc20_count = len(entry.get("erc20_balances", []))
                if chain_count > 0 or erc20_count > 0:
                    hits.append({
                        "time_str": time.strftime("%H:%M:%S", time.localtime(entry.get("timestamp", 0))),
                        "address": entry.get("address", "?"),
                        "chain_count": chain_count,
                        "erc20_count": erc20_count,
                    })
            except Exception:
                pass
            if len(hits) >= n:
                break
    except Exception:
        pass
    return hits


@app.route("/")
def index():
    stats = read_stats()
    logs = read_logs()
    hits = read_hits()
    return render_template_string(HTML_TEMPLATE, stats=stats, logs=logs, hits=hits)


@app.route("/api/stats")
def api_stats():
    stats = read_stats()
    stats["hits_list"] = read_hits(10)
    return jsonify(stats)


@app.route("/api/logs")
def api_logs():
    return jsonify(read_logs(100))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    log_msg = f"Viewer starting on port {port}"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(VIEWER_LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {log_msg}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

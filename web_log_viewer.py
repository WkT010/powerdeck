#!/usr/bin/env python3
"""Web 日志查看器：端口 8080，提供实时日志/速度卡片/命中列表。"""

import json
import os
import time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

OUTPUT_DIR = Path("/workspace/output")
STATS_FILE = OUTPUT_DIR / "stats.json"
HITS_FILE  = OUTPUT_DIR / "found_wallets.jsonl"
LOG_FILE   = OUTPUT_DIR / "scanner.log"
VIEWER_LOG = OUTPUT_DIR / "viewer.log"

PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("VIEWER_HOST", "0.0.0.0")


def read_stats():
    try:
        return json.loads(STATS_FILE.read_text())
    except Exception:
        return {}


def read_recent_hits(limit=50):
    hits = []
    try:
        with open(HITS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        hits.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except FileNotFoundError:
        pass
    return hits[-limit:]


def read_recent_log(lines=100):
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except FileNotFoundError:
        return "(no scanner.log yet)"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scanner Dashboard</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'SF Mono', 'Consolas', monospace; background: #0d1117; color: #c9d1d9; padding: 20px; }}
  h1 {{ color: #58a6ff; margin-bottom: 16px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 20px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }}
  .card .label {{ font-size: 12px; color: #8b949e; text-transform: uppercase; }}
  .card .value {{ font-size: 24px; color: #58a6ff; font-weight: bold; margin-top: 4px; }}
  .card.hit .value {{ color: #f0883e; }}
  .section {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
  .section h2 {{ color: #58a6ff; font-size: 16px; margin-bottom: 10px; }}
  pre {{ white-space: pre-wrap; word-break: break-all; font-size: 13px; max-height: 400px; overflow-y: auto; color: #8b949e; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 6px 10px; border-bottom: 1px solid #30363d; text-align: left; }}
  th {{ color: #58a6ff; }}
  .auto-refresh {{ position: fixed; top: 10px; right: 20px; font-size: 12px; color: #8b949e; }}
</style>
</head>
<body>
<div class="auto-refresh">Auto-refresh: 5s</div>
<h1>Scanner Dashboard</h1>

<div class="cards">
  <div class="card"><div class="label">扫描速度(全程)</div><div class="value" id="rate_total">{rate_total} addr/s</div></div>
  <div class="card"><div class="label">扫描速度(近30s)</div><div class="value" id="rate_recent">{rate_recent} addr/s</div></div>
  <div class="card"><div class="label">计算速度</div><div class="value" id="keygen">{keygen} keys/s</div></div>
  <div class="card"><div class="label">累计扫描</div><div class="value" id="scanned">{scanned}</div></div>
  <div class="card hit"><div class="label">命中</div><div class="value" id="hits">{hits}</div></div>
  <div class="card"><div class="label">运行时间</div><div class="value" id="runtime">{runtime}s</div></div>
</div>

<div class="section">
  <h2>Scanner Log (最新100行)</h2>
  <pre id="log">{log_content}</pre>
</div>

<div class="section">
  <h2>命中列表 (最近50条)</h2>
  <table>
    <tr><th>时间</th><th>地址</th><th>链/类型</th><th>余额(wei)</th></tr>
    {hits_rows}
  </table>
</div>

<script>
setTimeout(() => location.reload(), 5000);
</script>
</body>
</html>"""


class ViewerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return

        stats = read_stats()
        rate_total  = stats.get("scan_rate_total_addr_per_sec", 0)
        rate_recent = stats.get("scan_rate_recent_addr_per_sec", 0)
        keygen      = stats.get("keygen_rate_keys_per_sec", 0)
        scanned     = stats.get("scanned", 0)
        hits_count  = stats.get("hits", 0)
        runtime     = stats.get("total_running_sec", 0)

        log_content = read_recent_log()
        log_escaped = log_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        recent_hits = read_recent_hits()
        hits_rows = ""
        for h in recent_hits:
            addr = h.get("address", "")
            ts = h.get("timestamp", "")
            for detail in h.get("hits", []):
                chain = detail.get("chain", "")
                dtype = detail.get("type", "")
                bal = detail.get("balance_wei", "0")
                hits_rows += f"<tr><td>{ts}</td><td>{addr[:10]}…</td><td>{chain}/{dtype}</td><td>{bal}</td></tr>"

        html = HTML_TEMPLATE.format(
            rate_total=rate_total,
            rate_recent=rate_recent,
            keygen=keygen,
            scanned=scanned,
            hits=hits_count,
            runtime=runtime,
            log_content=log_escaped,
            hits_rows=hits_rows or "<tr><td colspan='4'>暂无命中</td></tr>",
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        # 写入 viewer.log
        with open(VIEWER_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {format % args}\n")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server = HTTPServer((HOST, PORT), ViewerHandler)
    print(f"viewer 启动 http://{HOST}:{PORT}/")
    with open(VIEWER_LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} viewer started on {HOST}:{PORT}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()


if __name__ == "__main__":
    main()

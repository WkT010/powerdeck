#!/usr/bin/env python3
import os
import sys
import json
import time
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

OUTPUT_DIR = Path("/workspace/output")
STATS_FILE = OUTPUT_DIR / "stats.json"
FOUND_WALLETS = OUTPUT_DIR / "found_wallets.jsonl"
SCANNER_LOG = OUTPUT_DIR / "scanner.log"
VIEWER_LOG = OUTPUT_DIR / "viewer.log"
PID_FILE = Path("/workspace/.viewer.pid")
PORT = int(os.environ.get("PORT", "8080"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(VIEWER_LOG), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("viewer")


def read_json_safe(path):
    try:
        with open(str(path), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def read_lines_safe(path, max_lines=100):
    try:
        with open(str(path), "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return lines[-max_lines:]
    except FileNotFoundError:
        return []


def read_jsonl_safe(path, max_entries=50):
    entries = []
    try:
        with open(str(path), "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[-max_entries:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return entries


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="10">
<title>Scanner Dashboard</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }}
  h1 {{ font-size: 20px; margin-bottom: 16px; color: #58a6ff; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 20px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }}
  .card .label {{ font-size: 12px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; }}
  .card .value {{ font-size: 24px; font-weight: 700; margin-top: 6px; }}
  .card .unit {{ font-size: 12px; color: #8b949e; margin-left: 4px; }}
  .section {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin-bottom: 20px; }}
  .section h2 {{ font-size: 16px; margin-bottom: 12px; color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 8px; }}
  .log {{ font-family: "SF Mono", Consolas, monospace; font-size: 12px; line-height: 1.6; background: #0d1117; padding: 12px; border-radius: 4px; max-height: 300px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ background: #21262d; color: #8b949e; padding: 8px; text-align: left; font-weight: 600; }}
  td {{ padding: 8px; border-bottom: 1px solid #21262d; word-break: break-all; }}
  tr:hover {{ background: #1f2428; }}
  .hit-badge {{ background: #1f6feb; color: #fff; padding: 2px 6px; border-radius: 3px; font-size: 11px; }}
  .refresh-info {{ color: #8b949e; font-size: 11px; margin-bottom: 12px; }}
  .addr {{ font-family: monospace; font-size: 11px; color: #58a6ff; }}
</style>
</head>
<body>
<h1>Multi-Chain Private Key Scanner Dashboard</h1>
<p class="refresh-info">Auto-refresh every 10s. Last update: {{last_update}}</p>

<div class="grid">
  <div class="card"><div class="label">Scan Speed (Total)</div><div class="value">{{scan_rate_total}}<span class="unit">addr/s</span></div></div>
  <div class="card"><div class="label">Scan Speed (Recent 30s)</div><div class="value">{{scan_rate_recent}}<span class="unit">addr/s</span></div></div>
  <div class="card"><div class="label">KeyGen Speed</div><div class="value">{{keygen_rate}}<span class="unit">keys/s</span></div></div>
  <div class="card"><div class="label">Total Scanned</div><div class="value">{{scanned}}</div></div>
  <div class="card"><div class="label">Hits Found</div><div class="value">{{hits}}</div></div>
  <div class="card"><div class="label">Runtime</div><div class="value">{{runtime}}<span class="unit">s</span></div></div>
</div>

<div class="section">
  <h2>Recent Logs</h2>
  <div class="log">{{logs}}</div>
</div>

<div class="section">
  <h2>Recent Hits</h2>
  {{hits_table}}
</div>

</body>
</html>"""


def build_html():
    stats = read_json_safe(STATS_FILE) or {}
    logs = read_lines_safe(SCANNER_LOG, 80)
    logs_text = "".join(logs) if logs else "(no logs yet)"

    hits = read_jsonl_safe(FOUND_WALLETS, 30)
    if hits:
        rows = ""
        for h in reversed(hits):
            ts = h.get("timestamp", "?")
            addr = h.get("address", "?")
            hit_list = h.get("hits", [])
            hit_names = ", ".join(f"{x.get('chain','?')}:{x.get('asset','?')}" for x in hit_list)
            rows += f"<tr><td class='addr'>{addr}</td><td><span class='hit-badge'>{len(hit_list)} hits</span></td><td>{hit_names}</td><td style='color:#8b949e'>{ts}</td></tr>\n"
        hits_table = f"<table><tr><th>Address</th><th>Hits</th><th>Assets</th><th>Time</th></tr>{rows}</table>"
    else:
        hits_table = "<p style='color:#8b949e'>No hits yet.</p>"

    last_update = stats.get("last_update", "N/A")
    if last_update:
        last_update = last_update.replace("T", " ")[:19]

    return HTML_TEMPLATE.format(
        last_update=last_update,
        scan_rate_total=f"{stats.get('scan_rate_total_addr_per_sec', 0.0):.2f}",
        scan_rate_recent=f"{stats.get('scan_rate_recent_addr_per_sec', 0.0):.2f}",
        keygen_rate=f"{stats.get('keygen_rate_keys_per_sec', 0.0):.1f}",
        scanned=stats.get("scanned", 0),
        hits=stats.get("hits", 0),
        runtime=f"{stats.get('total_running_sec', 0):.0f}",
        logs=logs_text,
        hits_table=hits_table,
    )


class ViewerHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path in ("", "/"):
            self._respond_html(build_html())
        elif path == "/health":
            self._respond_json({"status": "ok", "time": time.time()})
        elif path == "/api/stats":
            self._respond_json(read_json_safe(STATS_FILE) or {})
        elif path == "/api/logs":
            self._respond_json(read_lines_safe(SCANNER_LOG, 100))
        elif path == "/api/hits":
            self._respond_json(read_jsonl_safe(FOUND_WALLETS, 100))
        else:
            self._respond_error(404, "Not Found")

    def _respond_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_error(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg.encode())

    def log_message(self, fmt, *args):
        logger.info("VIEWER: %s - %s", self.address_string(), fmt % args)


def save_pid():
    PID_FILE.write_text(str(os.getpid()))


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_pid()
    logger.info("Viewer starting on port %d (PID=%d)", PORT, os.getpid())

    server = HTTPServer(("0.0.0.0", PORT), ViewerHandler)
    logger.info("Viewer listening on 0.0.0.0:%d", PORT)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Viewer stopped by user")
        server.shutdown()
    except Exception as e:
        logger.error("Viewer crashed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

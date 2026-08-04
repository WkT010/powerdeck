#!/usr/bin/env python3
"""Web log viewer for scanner status.
Serves on port 8080, providing real-time logs, speed cards, and hit list.
"""

import os
import sys
import json
import time
import http.server
import socketserver
from pathlib import Path

PORT = int(os.environ.get("PORT", "8080"))
OUTPUT_DIR = Path("/workspace/output")
STATS_FILE = OUTPUT_DIR / "stats.json"
FOUND_FILE = OUTPUT_DIR / "found_wallets.jsonl"
LOG_FILE = OUTPUT_DIR / "scanner.log"

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scanner Dashboard</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0f1117; color: #e4e4e7; padding: 20px; min-height: 100vh; }}
  h1 {{ font-size: 20px; margin-bottom: 16px; color: #a78bfa; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 20px; }}
  .card {{ background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 8px; padding: 14px; }}
  .card .label {{ font-size: 12px; color: #8b8d98; text-transform: uppercase; letter-spacing: 0.5px; }}
  .card .value {{ font-size: 24px; font-weight: 600; margin-top: 4px; color: #22d3ee; }}
  .card.hits .value {{ color: #f59e0b; }}
  .card.scanned .value {{ color: #22c55e; }}
  .section {{ background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
  .section h2 {{ font-size: 14px; color: #8b8d98; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }}
  pre {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px;
        background: #0a0b10; padding: 12px; border-radius: 6px; overflow-x: auto;
        max-height: 300px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ text-align: left; padding: 8px; color: #8b8d98; border-bottom: 1px solid #2a2d3a; font-weight: 500; }}
  td {{ padding: 8px; border-bottom: 1px solid #1e2029; font-family: 'SF Mono', monospace; }}
  .empty {{ color: #555; font-size: 13px; text-align: center; padding: 20px; }}
  .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
  .dot.on {{ background: #22c55e; box-shadow: 0 0 6px #22c55e; }}
  .dot.off {{ background: #ef4444; }}
  .meta {{ font-size: 11px; color: #6b6e7a; margin-top: 8px; }}
</style>
</head>
<body>
  <h1><span class="dot {status_dot}"></span>Multi-Chain Scanner Dashboard</h1>
  <div class="grid">
    <div class="card"><div class="label">Scan Rate (Total)</div><div class="value">{rate_total}</div></div>
    <div class="card"><div class="label">Scan Rate (30s)</div><div class="value">{rate_recent}</div></div>
    <div class="card"><div class="label">KeyGen Rate</div><div class="value">{keygen_rate}</div></div>
    <div class="card scanned"><div class="label">Scanned</div><div class="value">{scanned}</div></div>
    <div class="card hits"><div class="label">Hits</div><div class="value">{hits}</div></div>
    <div class="card"><div class="label">Runtime</div><div class="value">{runtime}</div></div>
  </div>
  <div class="section">
    <h2>Recent Logs</h2>
    <pre>{log_content}</pre>
  </div>
  <div class="section">
    <h2>Found Wallets (Recent 50)</h2>
    {found_table}
  </div>
  <div class="meta">Last updated: {last_update}</div>
  <script>setTimeout(() => location.reload(), 3000);</script>
</body>
</html>"""


def read_file_lines(path: Path, max_lines: int = 50) -> str:
    if not path.exists():
        return "(file not found)"
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:])
    except Exception as e:
        return f"(error: {e})"


def read_found_jsonl(path: Path, max_lines: int = 50) -> list[dict]:
    if not path.exists():
        return []
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        items = []
        for line in lines[-max_lines:]:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return items
    except Exception:
        return []


def read_stats(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def generate_page() -> str:
    stats = read_stats(STATS_FILE)
    log_content = read_file_lines(LOG_FILE, 30)
    found_items = read_found_jsonl(FOUND_FILE, 50)

    if found_items:
        rows = "".join(
            f"<tr><td>{i.get('ts','')[:19]}</td>"
            f"<td>{i.get('address','')[:12]}...</td>"
            f"<td>{i.get('chain','')}</td>"
            f"<td>{i.get('asset','')}</td>"
            f"<td>{i.get('balance',0):.6f}</td></tr>"
            for i in found_items
        )
        found_table = (
            '<table><tr><th>Time</th><th>Address</th><th>Chain</th><th>Asset</th><th>Balance</th></tr>'
            + rows + '</table>'
        )
    else:
        found_table = '<div class="empty">No hits yet</div>'

    last_update = stats.get("last_update", "N/A")
    scan_rate = stats.get("scan_rate_total_addr_per_sec", 0)
    scan_recent = stats.get("scan_rate_recent_addr_per_sec", 0)
    keygen_rate = stats.get("keygen_rate_keys_per_sec", 0)
    scanned = stats.get("scanned", 0)
    hits = stats.get("hits", 0)
    runtime = stats.get("total_running_sec", 0)

    dot_class = "on" if scanned > 0 else "off"

    return PAGE_TEMPLATE.format(
        status_dot=dot_class,
        rate_total=f"{scan_rate:.1f} addr/s",
        rate_recent=f"{scan_recent:.1f} addr/s",
        keygen_rate=f"{keygen_rate:.1f} keys/s",
        scanned=f"{scanned:,}",
        hits=f"{hits:,}",
        runtime=f"{runtime:.0f}s",
        log_content=log_content,
        found_table=found_table,
        last_update=last_update,
    )


class ViewerHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            content = generate_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif self.path == "/api/stats":
            stats = read_stats(STATS_FILE)
            content = json.dumps(stats).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/api/found":
            items = read_found_jsonl(FOUND_FILE, 100)
            content = json.dumps(items).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("0.0.0.0", PORT), ViewerHandler)
    print(f"Viewer running on http://0.0.0.0:{PORT}/")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()

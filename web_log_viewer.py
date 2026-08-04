#!/usr/bin/env python3
"""Web 日志查看器：端口 8080，提供实时日志/速度卡片/命中列表"""

import json
import os
import time
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

# ── 配置 ──────────────────────────────────────────────
PORT = int(os.environ.get("PORT", "8080"))
OUTPUT_DIR = Path("/workspace/output")
STATS_FILE  = OUTPUT_DIR / "stats.json"
LOG_FILE    = OUTPUT_DIR / "scanner.log"
HITS_FILE   = OUTPUT_DIR / "found_wallets.jsonl"
VIEWER_LOG  = OUTPUT_DIR / "viewer.log"
PID_FILE    = Path("/workspace/.viewer.pid")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(VIEWER_LOG, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("viewer")

# ── 数据读取 ──────────────────────────────────────────
def load_stats() -> dict:
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "scanned": 0, "hits": 0, "total_running_sec": 0,
            "scan_rate_total_addr_per_sec": 0.0,
            "scan_rate_recent_addr_per_sec": 0.0,
            "keygen_rate_keys_per_sec": 0.0,
        }

def load_recent_log(n: int = 50) -> list:
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception:
        return []

def load_recent_hits(n: int = 20) -> list:
    try:
        lines = HITS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        results = []
        for line in lines[-n:]:
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return results
    except Exception:
        return []

# ── HTML 页面 ─────────────────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scanner Dashboard</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace; background:#0d1117; color:#c9d1d9; padding:20px; }
  h1 { color:#58a6ff; margin-bottom:16px; font-size:1.5em; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-bottom:24px; }
  .card { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; }
  .card .label { color:#8b949e; font-size:0.8em; text-transform:uppercase; letter-spacing:1px; }
  .card .value { color:#58a6ff; font-size:1.8em; font-weight:bold; margin-top:4px; }
  .card .unit { color:#8b949e; font-size:0.7em; }
  .section { margin-bottom:24px; }
  .section h2 { color:#8b949e; font-size:1em; margin-bottom:8px; border-bottom:1px solid #30363d; padding-bottom:4px; }
  .log-box { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px; max-height:350px; overflow-y:auto; font-size:0.8em; line-height:1.6; white-space:pre-wrap; word-break:break-all; }
  .hit-item { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px; margin-bottom:8px; font-size:0.8em; }
  .hit-item .addr { color:#3fb950; font-weight:bold; }
  .hit-item .chain { color:#d29922; margin-left:8px; }
  .refresh-hint { color:#484f58; font-size:0.75em; margin-top:4px; }
  #hits-container:empty::before { content:'暂无命中记录'; color:#484f58; }
</style>
</head>
<body>
<h1>Scanner Dashboard</h1>
<div class="cards" id="stats-cards"></div>
<div class="section">
  <h2>Scanner Log (最近 50 行)</h2>
  <div class="log-box" id="log-box">Loading...</div>
</div>
<div class="section">
  <h2>命中列表 (最近 20 条)</h2>
  <div id="hits-container"></div>
</div>
<p class="refresh-hint">自动刷新间隔: 3 秒</p>
<script>
async function refresh(){
  try{
    const s=await(await fetch('/api/stats')).json();
    document.getElementById('stats-cards').innerHTML=[
      ['扫描速度(全程)',s.scan_rate_total_addr_per_sec,'addr/s'],
      ['扫描速度(近30)',s.scan_rate_recent_addr_per_sec,'addr/s'],
      ['计算速度',s.keygen_rate_keys_per_sec,'keys/s'],
      ['累计扫描',s.scanned,''],
      ['命中',s.hits,''],
      ['运行时间',s.total_running_sec,'s'],
    ].map(([l,v,u])=>`<div class="card"><div class="label">${l}</div><div class="value">${v}<span class="unit"> ${u}</span></div></div>`).join('');
  }catch(e){}
  try{
    const r=await(await fetch('/api/log')).json();
    document.getElementById('log-box').textContent=r.lines.join('\\n');
  }catch(e){}
  try{
    const h=await(await fetch('/api/hits')).json();
    document.getElementById('hits-container').innerHTML=h.hits.map(x=>
      `<div class="hit-item"><span class="addr">${x.address||''}</span>${(x.chains||[]).filter(c=>c.balance_eth>0).map(c=>`<span class="chain">${c.chain}: ${c.balance_eth.toFixed(6)}</span>`).join('')}<div style="color:#484f58;margin-top:2px">${x.timestamp||''}</div></div>`
    ).join('');
  }catch(e){}
}
refresh(); setInterval(refresh,3000);
</script>
</body>
</html>"""

# ── HTTP Handler ───────────────────────────────────────
class ViewerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/stats":
            self._serve_json(load_stats())
        elif self.path == "/api/log":
            self._serve_json({"lines": load_recent_log(50)})
        elif self.path == "/api/hits":
            self._serve_json({"hits": load_recent_hits(20)})
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        data = HTML_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        # 抑制默认的 stderr 日志
        pass

# ── 入口 ──────────────────────────────────────────────
def main():
    pid = os.getpid()
    PID_FILE.write_text(str(pid))
    log.info("Viewer PID=%d written to %s, starting on :%d", pid, PID_FILE, PORT)

    server = HTTPServer(("0.0.0.0", PORT), ViewerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Viewer stopped by user")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 日志查看器 — 基于 Python 内置 http.server。

提供实时日志、速度统计卡片与命中记录展示的深色主题控制台。
"""

import os
import sys
import json
import atexit
import logging
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# ----------------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------------
BASE_DIR = "/workspace"
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
SCANNER_LOG = os.path.join(OUTPUT_DIR, "scanner.log")
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
HITS_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
VIEWER_LOG = os.path.join(OUTPUT_DIR, "viewer.log")
PID_FILE = os.path.join(BASE_DIR, ".viewer.pid")

PORT = int(os.environ.get("PORT", "8080"))
LOG_TAIL_LINES = 50
HITS_LIMIT = 20

# ----------------------------------------------------------------------------
# 日志
# ----------------------------------------------------------------------------
logger = logging.getLogger("viewer")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

_file_handler = logging.FileHandler(VIEWER_LOG, encoding="utf-8")  # 追加模式
_file_handler.setFormatter(_fmt)
logger.addHandler(_file_handler)

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_fmt)
logger.addHandler(_stream_handler)


# ----------------------------------------------------------------------------
# 数据读取辅助
# ----------------------------------------------------------------------------
def read_tail(path, n=LOG_TAIL_LINES):
    """读取文件末尾 n 行。文件不存在或异常时返回空列表。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return list(deque(f, maxlen=n))
    except FileNotFoundError:
        logger.warning("日志文件不存在: %s", path)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("读取日志失败 %s: %s", path, exc)
        return []


def read_stats():
    """读取 stats.json。文件缺失时返回带默认值的字典，保证前端不崩。"""
    defaults = {
        "scan_rate_total": 0,
        "scan_rate_recent": 0,
        "keygen_rate": 0,
        "error": None,
    }
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            defaults.update(data)
        else:
            defaults["error"] = "stats.json 格式异常"
        return defaults
    except FileNotFoundError:
        defaults["error"] = "stats.json 尚未生成"
        return defaults
    except Exception as exc:  # noqa: BLE001
        defaults["error"] = "读取 stats.json 失败: %s" % exc
        return defaults


def read_hits(limit=HITS_LIMIT):
    """读取 found_wallets.jsonl 最近 limit 条记录，按时间倒序（最新在前）。"""
    hits = []
    try:
        with open(HITS_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                hits.append(json.loads(line))
            except json.JSONDecodeError:
                hits.append({"raw": line})
        hits.reverse()  # 最新在前
    except FileNotFoundError:
        logger.info("命中文件不存在: %s", HITS_FILE)
    except Exception as exc:  # noqa: BLE001
        logger.error("读取命中文件失败 %s: %s", HITS_FILE, exc)
    return hits


# ----------------------------------------------------------------------------
# HTML 页面
# ----------------------------------------------------------------------------
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scanner Console — 实时日志查看器</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Sora:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#1a1a2e;
    --bg-deep:#131324;
    --panel:rgba(31,41,64,.55);
    --panel-solid:#1f2940;
    --border:rgba(100,255,218,.12);
    --border-strong:rgba(100,255,218,.28);
    --text:#e6f1ff;
    --text-dim:#8892b0;
    --accent:#64ffda;
    --gold:#ffd166;
    --danger:#ff6b6b;
    --shadow:0 18px 50px -18px rgba(0,0,0,.6);
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0}
  body{
    font-family:'Sora',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    color:var(--text);
    background-color:var(--bg);
    background-image:
      radial-gradient(ellipse 85% 55% at 50% -18%, rgba(100,255,218,.10), transparent 70%),
      radial-gradient(ellipse 60% 40% at 100% 0%, rgba(255,209,102,.06), transparent 70%),
      linear-gradient(rgba(255,255,255,.015) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,.015) 1px, transparent 1px);
    background-size:100% 100%,100% 100%,42px 42px,42px 42px;
    background-attachment:fixed;
    min-height:100vh;
    line-height:1.5;
  }
  .wrap{max-width:1320px;margin:0 auto;padding:26px 22px 48px}

  /* Header */
  header.top{
    display:flex;align-items:center;justify-content:space-between;gap:16px;
    flex-wrap:wrap;margin-bottom:26px;
  }
  .brand{display:flex;align-items:center;gap:14px}
  .logo{
    width:42px;height:42px;border-radius:11px;flex:none;
    background:linear-gradient(145deg,rgba(100,255,218,.22),rgba(100,255,218,.04));
    border:1px solid var(--border-strong);
    display:grid;place-items:center;color:var(--accent);
    font-family:'JetBrains Mono';font-weight:700;font-size:18px;
    box-shadow:0 0 22px -6px rgba(100,255,218,.5);
  }
  .brand h1{font-size:20px;font-weight:700;margin:0;letter-spacing:.01em}
  .brand .sub{font-size:12px;color:var(--text-dim);letter-spacing:.16em;text-transform:uppercase}
  .meta{display:flex;align-items:center;gap:18px;font-family:'JetBrains Mono';font-size:13px;color:var(--text-dim)}
  .badge{display:inline-flex;align-items:center;gap:8px;padding:7px 13px;border-radius:999px;
    border:1px solid var(--border-strong);background:rgba(100,255,218,.06);color:var(--accent);font-size:12px;letter-spacing:.12em}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 12px var(--accent);animation:pulse 1.5s infinite}
  @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.75)}}

  /* Stats grid */
  .stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px}
  .card{
    position:relative;overflow:hidden;padding:22px 24px;border-radius:16px;
    background:var(--panel);border:1px solid var(--border);
    backdrop-filter:blur(10px);box-shadow:var(--shadow);
  }
  .card::before{content:"";position:absolute;inset:0 0 auto 0;height:2px;
    background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:.7}
  .card .label{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--text-dim)}
  .card .value-row{display:flex;align-items:baseline;gap:6px;margin-top:10px}
  .card .value{font-family:'JetBrains Mono';font-size:38px;font-weight:700;color:var(--accent);line-height:1;transition:color .2s}
  .card .unit{font-size:13px;color:var(--text-dim);font-family:'JetBrains Mono'}
  .card .desc{margin-top:8px;font-size:12px;color:var(--text-dim)}
  .card.gold::before{background:linear-gradient(90deg,transparent,var(--gold),transparent)}
  .card.gold .value{color:var(--gold)}
  .flash{animation:flash .6s ease}
  @keyframes flash{0%{color:#fff;text-shadow:0 0 22px var(--accent)}100%{text-shadow:none}}

  /* Content grid */
  .content-grid{display:grid;grid-template-columns:1.7fr 1fr;gap:16px}
  .panel{background:var(--panel);border:1px solid var(--border);border-radius:16px;
    backdrop-filter:blur(10px);box-shadow:var(--shadow);overflow:hidden;display:flex;flex-direction:column}
  .panel-head{display:flex;align-items:center;justify-content:space-between;gap:10px;
    padding:14px 18px;border-bottom:1px solid var(--border);background:rgba(0,0,0,.18)}
  .panel-head h2{margin:0;font-size:13px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--text)}
  .panel-head .tag{font-family:'JetBrains Mono';font-size:11px;color:var(--text-dim)}

  /* Log area */
  .log-area{
    font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12.5px;line-height:1.6;
    color:#c8d3f5;padding:16px 18px;height:470px;overflow-y:auto;
    background:linear-gradient(180deg,var(--bg-deep),#10101c);
  }
  .log-line{white-space:pre-wrap;word-break:break-all;padding:1px 0}
  .log-line.err{color:var(--danger)}
  .log-line.warn{color:var(--gold)}
  .log-line.hit{color:var(--accent)}
  .log-empty{color:var(--text-dim);font-style:italic}

  /* Hits */
  .hits-scroll{max-height:470px;overflow:auto}
  table.hits{width:100%;border-collapse:collapse;font-size:12.5px}
  table.hits th{text-align:left;color:var(--accent);font-weight:600;letter-spacing:.06em;
    padding:11px 14px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--panel-solid);z-index:1}
  table.hits td{padding:10px 14px;border-bottom:1px solid rgba(255,255,255,.04);
    font-family:'JetBrains Mono';color:var(--text);max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  table.hits tr:hover td{background:rgba(100,255,218,.05)}
  .empty-state{padding:40px 20px;text-align:center;color:var(--text-dim);font-size:13px}
  .empty-state .ic{font-family:'JetBrains Mono';font-size:26px;color:var(--border-strong);margin-bottom:8px}

  /* Scrollbars */
  ::-webkit-scrollbar{width:9px;height:9px}
  ::-webkit-scrollbar-track{background:transparent}
  ::-webkit-scrollbar-thumb{background:rgba(100,255,218,.18);border-radius:8px}
  ::-webkit-scrollbar-thumb:hover{background:rgba(100,255,218,.32)}

  footer.bottom{margin-top:26px;text-align:center;font-size:11px;color:var(--text-dim);
    font-family:'JetBrains Mono';letter-spacing:.08em}

  /* Responsive */
  @media (max-width:980px){
    .content-grid{grid-template-columns:1fr}
  }
  @media (max-width:680px){
    .stats-grid{grid-template-columns:1fr}
    .card .value{font-size:32px}
    .wrap{padding:18px 14px}
  }
</style>
</head>
<body>
<div class="wrap">

  <header class="top">
    <div class="brand">
      <div class="logo">◢</div>
      <div>
        <h1>Scanner Console</h1>
        <div class="sub">实时日志 · 速度监控 · 命中追踪</div>
      </div>
    </div>
    <div class="meta">
      <span id="clock">--:--:--</span>
      <span class="badge"><span class="dot"></span>LIVE</span>
    </div>
  </header>

  <!-- 速度卡片 -->
  <section class="stats-grid">
    <div class="card">
      <div class="label">Scan Rate · Total</div>
      <div class="value-row"><span class="value" id="stat-total">0</span><span class="unit">addr/s</span></div>
      <div class="desc">累计平均扫描速度</div>
    </div>
    <div class="card">
      <div class="label">Scan Rate · Recent</div>
      <div class="value-row"><span class="value" id="stat-recent">0</span><span class="unit">addr/s</span></div>
      <div class="desc">近期瞬时扫描速度</div>
    </div>
    <div class="card gold">
      <div class="label">Keygen Rate</div>
      <div class="value-row"><span class="value" id="stat-keygen">0</span><span class="unit">key/s</span></div>
      <div class="desc">密钥生成速率</div>
    </div>
  </section>

  <!-- 日志 + 命中 -->
  <section class="content-grid">
    <div class="panel">
      <div class="panel-head">
        <h2>实时日志</h2>
        <span class="tag" id="log-tag">tail -n 50 · refresh 3s</span>
      </div>
      <div class="log-area" id="log"><div class="log-empty">正在加载日志…</div></div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <h2>命中记录</h2>
        <span class="tag" id="hits-tag">最近 20 条</span>
      </div>
      <div class="hits-scroll">
        <table class="hits">
          <thead id="hits-head"></thead>
          <tbody id="hits-body"></tbody>
        </table>
        <div class="empty-state" id="hits-empty">
          <div class="ic">∅</div>
          <div>暂无命中记录，扫描器持续运行中…</div>
        </div>
      </div>
    </div>
  </section>

  <footer class="bottom">web_log_viewer.py · port <span id="port">PORT</span> · pid <span id="pid">PID</span></footer>
</div>

<script>
(function(){
  "use strict";
  var logEl   = document.getElementById('log');
  var autoScroll = true;

  // ---- helpers ----
  function esc(s){return String(s).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function fmtRate(v){
    var n = Number(v); if(isNaN(n)) n = 0;
    if(n >= 1e9) return (n/1e9).toFixed(2)+'B';
    if(n >= 1e6) return (n/1e6).toFixed(2)+'M';
    if(n >= 1e3) return (n/1e3).toFixed(2)+'K';
    return Math.round(n).toLocaleString();
  }
  function trunc(s,n){n=n||28;return s.length>n? s.slice(0,n)+'…':s;}
  function classify(line){
    var l=line.toLowerCase();
    if(/error|fatal|fail|exception/.test(l)) return 'err';
    if(/warn/.test(l)) return 'warn';
    if(/found|hit|match|balance/.test(l)) return 'hit';
    return '';
  }

  // ---- stats ----
  function setStat(id,val){
    var el=document.getElementById(id);
    var f=fmtRate(val);
    if(el.textContent!==f){el.textContent=f;el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash');}
  }
  function fetchStats(){
    fetch('/api/stats',{cache:'no-store'}).then(function(r){return r.json();}).then(function(d){
      setStat('stat-total',  d.scan_rate_total_addr_per_sec || d.scan_rate_total || 0);
      setStat('stat-recent', d.scan_rate_recent_addr_per_sec || d.scan_rate_recent || 0);
      setStat('stat-keygen', d.keygen_rate_keys_per_sec || d.keygen_rate || 0);
    }).catch(function(){});
  }

  // ---- logs ----
  logEl.addEventListener('scroll',function(){
    autoScroll = (logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight) < 40;
  });
  function fetchLogs(){
    fetch('/api/logs',{cache:'no-store'}).then(function(r){return r.json();}).then(function(d){
      var lines=d.lines||[];
      if(!lines.length){logEl.innerHTML='<div class="log-empty">暂无日志输出，等待扫描器启动…</div>';return;}
      var frag=document.createDocumentFragment();
      lines.forEach(function(line){
        var div=document.createElement('div');
        div.className='log-line '+classify(line);
        div.textContent=line;
        frag.appendChild(div);
      });
      logEl.innerHTML='';
      logEl.appendChild(frag);
      if(autoScroll) logEl.scrollTop=logEl.scrollHeight;
    }).catch(function(){});
  }

  // ---- hits ----
  function fetchHits(){
    fetch('/api/hits',{cache:'no-store'}).then(function(r){return r.json();}).then(function(d){
      var hits=d.hits||[];
      var head=document.getElementById('hits-head');
      var body=document.getElementById('hits-body');
      var empty=document.getElementById('hits-empty');
      if(!hits.length){
        head.innerHTML='';body.innerHTML='';empty.style.display='block';return;
      }
      empty.style.display='none';
      var keys=Object.keys(hits[0]);
      head.innerHTML='<tr>'+keys.map(function(k){return '<th>'+esc(k)+'</th>';}).join('')+'</tr>';
      body.innerHTML=hits.map(function(h){
        return '<tr>'+keys.map(function(k){
          var v=h[k]==null?'':String(h[k]);
          return '<td title="'+esc(v)+'">'+esc(trunc(v))+'</td>';
        }).join('')+'</tr>';
      }).join('');
    }).catch(function(){});
  }

  // ---- clock ----
  function tick(){
    var d=new Date();
    function p(n){return (n<10?'0':'')+n;}
    document.getElementById('clock').textContent=p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());
  }

  // ---- boot ----
  fetchStats(); fetchLogs(); fetchHits(); tick();
  setInterval(fetchStats,3000);
  setInterval(fetchLogs,3000);
  setInterval(fetchHits,3000);
  setInterval(tick,1000);
})();
</script>
</body>
</html>
"""


# ----------------------------------------------------------------------------
# HTTP 处理器
# ----------------------------------------------------------------------------
class ViewerHandler(BaseHTTPRequestHandler):
    server_version = "WebLogViewer/1.0"

    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _send_html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_html(HTML_PAGE)
        elif path == "/api/stats":
            self._send_json(read_stats())
        elif path == "/api/logs":
            self._send_json({"lines": read_tail(SCANNER_LOG, LOG_TAIL_LINES)})
        elif path == "/api/hits":
            self._send_json({"hits": read_hits(HITS_LIMIT)})
        else:
            self._send_json({"error": "not found", "path": path}, 404)

    def do_HEAD(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()


# ----------------------------------------------------------------------------
# 启动
# ----------------------------------------------------------------------------
def _cleanup():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:  # noqa: BLE001
        pass


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    atexit.register(_cleanup)

    server = ThreadingHTTPServer(("0.0.0.0", PORT), ViewerHandler)
    logger.info("Web 日志查看器已启动 — http://0.0.0.0:%d  (pid=%d)", PORT, os.getpid())
    logger.info("PID 已写入 %s", PID_FILE)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止…")
    finally:
        server.server_close()
        logger.info("Web 日志查看器已停止")


if __name__ == "__main__":
    main()

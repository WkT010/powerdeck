#!/usr/bin/env python3
"""
Ethereum Scanner - Web Log Viewer
=================================
轻量级 Web 日志查看器，纯标准库实现，无外部依赖。

功能：
  - 实时日志流（每 2 秒轮询，自动滚动到底部）
  - 速度指标卡片（扫描速度全程/近30、计算速度、累计扫描数、命中数、运行时长）
  - 命中记录列表（found_wallets.jsonl）
  - 进程状态指示

启动：
  python3 web_log_viewer.py            # 默认 0.0.0.0:8080
  PORT=9000 python3 web_log_viewer.py  # 自定义端口

访问：
  http://<host>:8080/
"""

import json
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_FILE = OUTPUT_DIR / "scanner.log"
STATS_FILE = OUTPUT_DIR / "stats.json"
FOUND_FILE = OUTPUT_DIR / "found_wallets.jsonl"
PID_FILE = BASE_DIR / ".scanner.pid"

PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0")
LOG_TAIL_DEFAULT = 200


# ============================================================
#                       数据读取
# ============================================================

def read_stats() -> dict:
    if not STATS_FILE.exists():
        return {}
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_log_tail(n: int = LOG_TAIL_DEFAULT) -> str:
    if not LOG_FILE.exists():
        return "(日志文件尚未生成)"
    try:
        # 用 tail 读取末尾 n 行，避免大文件全读
        out = subprocess.run(
            ["tail", "-n", str(n), str(LOG_FILE)],
            capture_output=True, text=True, timeout=3,
        )
        return out.stdout or "(空)"
    except Exception as e:
        return f"(读取日志失败: {e})"


def read_hits(limit: int = 50) -> list:
    if not FOUND_FILE.exists():
        return []
    try:
        lines = FOUND_FILE.read_text(encoding="utf-8").splitlines()
        # 取最后 limit 条
        tail = lines[-limit:] if len(lines) > limit else lines
        result = []
        for line in reversed(tail):  # 最新的排前面
            try:
                result.append(json.loads(line))
            except Exception:
                continue
        return result
    except Exception:
        return []


def check_scanner_alive() -> dict:
    """检查 scanner 进程是否存活。"""
    pid = None
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
        except Exception:
            pid = None
    alive = False
    etime = "-"
    if pid:
        try:
            out = subprocess.run(
                ["ps", "-p", str(pid), "-o", "etime="],
                capture_output=True, text=True, timeout=2,
            )
            if out.returncode == 0 and out.stdout.strip():
                alive = True
                etime = out.stdout.strip().split()[0]
        except Exception:
            pass
    return {"alive": alive, "pid": pid, "etime": etime}


# ============================================================
#                       HTTP 处理
# ============================================================

class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str = "text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send(200, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/" or path == "/index.html":
            self._send(200, HTML_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/state":
            n = LOG_TAIL_DEFAULT
            try:
                n = int(self.path.split("tail=")[1].split("&")[0])
                n = max(10, min(2000, n))
            except Exception:
                pass
            self._json({
                "ts": datetime.now(timezone.utc).isoformat(),
                "scanner": check_scanner_alive(),
                "stats": read_stats(),
                "log": read_log_tail(n),
                "hits": read_hits(50),
            })
        elif path == "/api/log":
            n = LOG_TAIL_DEFAULT
            try:
                n = int(self.path.split("tail=")[1].split("&")[0])
            except Exception:
                pass
            self._send(200, read_log_tail(n).encode("utf-8"), "text/plain; charset=utf-8")
        elif path == "/api/stats":
            self._json(read_stats())
        elif path == "/api/hits":
            self._json(read_hits(200))
        elif path == "/api/scanner":
            self._json(check_scanner_alive())
        elif path == "/favicon.ico":
            self._send(204, b"")
        else:
            self._send(404, b"Not Found")

    def log_message(self, *args):
        # 静默访问日志
        pass


# ============================================================
#                       HTML 页面
# ============================================================

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>多链私钥扫描器 - 实时监控</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", monospace;
    background: #0d1117; color: #c9d1d9; padding: 16px; font-size: 14px;
  }
  h1 { font-size: 18px; margin-bottom: 12px; color: #58a6ff; }
  .status-bar {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    margin-bottom: 12px; padding: 8px 12px; background: #161b22;
    border: 1px solid #30363d; border-radius: 6px;
  }
  .dot { width: 10px; height: 10px; border-radius: 50%; }
  .dot.alive { background: #3fb950; box-shadow: 0 0 6px #3fb950; }
  .dot.dead  { background: #f85149; }
  .dot.loading { background: #d29922; }
  .meta { color: #8b949e; font-size: 12px; }
  .grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 10px; margin-bottom: 12px;
  }
  .card {
    background: #161b22; border: 1px solid #30363d; border-radius: 6px;
    padding: 10px 12px;
  }
  .card .label { color: #8b949e; font-size: 11px; text-transform: uppercase; }
  .card .value { color: #58a6ff; font-size: 20px; font-weight: 600; margin-top: 4px; }
  .card .unit  { color: #8b949e; font-size: 12px; margin-left: 4px; }
  .card.hit .value { color: #3fb950; }
  .card.calc .value { color: #d29922; }
  .section { margin-bottom: 12px; }
  .section h2 { font-size: 14px; color: #8b949e; margin-bottom: 6px; }
  .controls { float: right; }
  .btn {
    background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
    padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px;
  }
  .btn:hover { background: #30363d; }
  .btn.active { background: #1f6feb; color: #fff; border-color: #1f6feb; }
  pre#log {
    background: #010409; border: 1px solid #30363d; border-radius: 6px;
    padding: 10px; height: 380px; overflow-y: auto; font-size: 12px;
    line-height: 1.5; white-space: pre-wrap; word-break: break-all;
  }
  .log-line { padding: 1px 0; }
  .log-line.warn { color: #d29922; }
  .log-line.err  { color: #f85149; }
  .log-line.info { color: #c9d1d9; }
  .log-line.hit  { color: #3fb950; font-weight: 600; }
  #hits { max-height: 240px; overflow-y: auto; }
  .hit-item {
    background: #161b22; border: 1px solid #30363d; border-radius: 4px;
    padding: 8px 10px; margin-bottom: 6px; font-size: 12px;
  }
  .hit-item .pk { color: #f85149; word-break: break-all; }
  .hit-item .addr { color: #58a6ff; word-break: break-all; }
  .hit-item .ts { color: #8b949e; font-size: 11px; }
  .hit-item .coins { color: #3fb950; margin-top: 4px; }
  .empty { color: #8b949e; font-style: italic; padding: 8px; }
  a { color: #58a6ff; }
</style>
</head>
<body>
  <h1>多链私钥扫描器 - 实时监控</h1>

  <div class="status-bar">
    <span id="dot" class="dot loading"></span>
    <span id="status-text">连接中...</span>
    <span class="meta" id="meta"></span>
    <span class="controls">
      <button class="btn" id="btn-pause">暂停刷新</button>
      <button class="btn" id="btn-scroll">自动滚动: 开</button>
      <button class="btn" id="btn-clear">清屏</button>
    </span>
  </div>

  <div class="grid" id="cards">
    <div class="card"><div class="label">累计扫描</div><div class="value" id="c-scanned">-</div></div>
    <div class="card hit"><div class="label">命中数</div><div class="value" id="c-hits">-</div></div>
    <div class="card"><div class="label">扫描速度(全程)</div><div class="value" id="c-rate-total">-<span class="unit">addr/s</span></div></div>
    <div class="card"><div class="label">扫描速度(近30)</div><div class="value" id="c-rate-recent">-<span class="unit">addr/s</span></div></div>
    <div class="card calc"><div class="label">计算速度</div><div class="value" id="c-keygen">-<span class="unit">keys/s</span></div></div>
    <div class="card"><div class="label">本次运行</div><div class="value" id="c-runtime">-<span class="unit">s</span></div></div>
  </div>

  <div class="section">
    <h2>实时日志 <span class="meta" id="log-ts"></span></h2>
    <pre id="log"></pre>
  </div>

  <div class="section">
    <h2>命中记录（最近 50 条）</h2>
    <div id="hits"></div>
  </div>

<script>
let paused = false;
let autoScroll = true;
let lastLog = "";

const $ = id => document.getElementById(id);

function fmt(n, d=2) {
  if (n === null || n === undefined) return "-";
  return (typeof n === "number") ? n.toFixed(d) : n;
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function classify(line) {
  const l = line.toLowerCase();
  if (l.includes('命中') || l.includes('⚡')) return 'hit';
  if (l.includes('[warning]') || l.includes('警告')) return 'warn';
  if (l.includes('[error]') || l.includes('异常')) return 'err';
  return 'info';
}

async function refresh() {
  if (paused) return;
  try {
    const r = await fetch('/api/state?tail=300&t=' + Date.now());
    const d = await r.json();
    // 状态条
    const s = d.scanner;
    $('dot').className = 'dot ' + (s.alive ? 'alive' : 'dead');
    $('status-text').textContent = s.alive
      ? `运行中 (PID=${s.pid})`
      : (s.pid ? `已停止 (PID=${s.pid} 不存在)` : '未运行');
    $('meta').textContent = s.alive ? `已运行 ${s.etime}` : '';

    // 卡片
    const st = d.stats || {};
    $('c-scanned').textContent = st.scanned ?? '-';
    $('c-hits').textContent = st.hits ?? '-';
    $('c-rate-total').innerHTML = fmt(st.scan_rate_total_addr_per_sec, 3) + '<span class="unit">addr/s</span>';
    $('c-rate-recent').innerHTML = fmt(st.scan_rate_recent_addr_per_sec, 3) + '<span class="unit">addr/s</span>';
    $('c-keygen').innerHTML = fmt(st.keygen_rate_keys_per_sec, 1) + '<span class="unit">keys/s</span>';
    $('c-runtime').innerHTML = fmt(st.total_running_sec, 0) + '<span class="unit">s</span>';

    // 日志
    const logBox = $('log');
    const wasAtBottom = logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 30;
    const lines = d.log.split('\n');
    logBox.innerHTML = lines.map(l => `<div class="log-line ${classify(l)}">${esc(l) || '&nbsp;'}</div>`).join('');
    if (autoScroll && wasAtBottom) logBox.scrollTop = logBox.scrollHeight;
    $('log-ts').textContent = '更新于 ' + new Date().toLocaleTimeString();

    // 命中
    const hitsBox = $('hits');
    if (!d.hits || d.hits.length === 0) {
      hitsBox.innerHTML = '<div class="empty">暂无命中记录（私钥空间 2^256，碰撞概率≈0，属预期）</div>';
    } else {
      hitsBox.innerHTML = d.hits.map(h => {
        const coins = (h.hits || []).map(x => `${x.chain}/${x.symbol||x.type}=${x.raw_balance}`).join('，');
        return `<div class="hit-item">
          <div class="ts">${esc(h.timestamp||'')}</div>
          <div>地址: <span class="addr">${esc(h.address||'')}</span></div>
          <div>私钥: <span class="pk">${esc(h.private_key||'')}</span></div>
          <div class="coins">${esc(coins)}</div>
        </div>`;
      }).join('');
    }
  } catch (e) {
    $('status-text').textContent = '连接失败: ' + e.message;
    $('dot').className = 'dot dead';
  }
}

$('btn-pause').onclick = function() {
  paused = !paused;
  this.textContent = paused ? '继续刷新' : '暂停刷新';
  this.classList.toggle('active', paused);
};
$('btn-scroll').onclick = function() {
  autoScroll = !autoScroll;
  this.textContent = '自动滚动: ' + (autoScroll ? '开' : '关');
  this.classList.toggle('active', autoScroll);
};
$('btn-clear').onclick = function() {
  $('log').innerHTML = '';
};

refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


# ============================================================
#                         入口
# ============================================================

def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[viewer] 监听 http://{HOST}:{PORT}/  (日志: {LOG_FILE})")
    print(f"[viewer] Ctrl+C 退出")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[viewer] 退出")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

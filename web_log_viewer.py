#!/usr/bin/env python3
"""
Web 日志查看器
提供实时日志、速度卡片、命中列表的 Web 界面
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
import threading

try:
    from aiohttp import web
except ImportError:
    print("请安装依赖: pip install aiohttp")
    sys.exit(1)

# 配置
OUTPUT_DIR = Path("/workspace/output")
PORT = int(os.getenv("PORT", "8080"))
HOST = os.getenv("HOST", "0.0.0.0")


class WebLogViewer:
    """Web 日志查看器"""

    def __init__(self):
        self.logger = self._setup_logger()
        self.app = web.Application()
        self._setup_routes()
        self.stats_cache = {}
        self.stats_lock = threading.Lock()

    def _setup_logger(self) -> logging.Logger:
        """配置日志"""
        logger = logging.getLogger("viewer")
        logger.setLevel(logging.INFO)

        # 文件处理器
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            OUTPUT_DIR / "viewer.log",
            mode="a",
            encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)

        return logger

    def _setup_routes(self):
        """设置路由"""
        self.app.router.add_get("/", self.index)
        self.app.router.add_get("/api/stats", self.api_stats)
        self.app.router.add_get("/api/logs/scanner", self.api_scanner_logs)
        self.app.router.add_get("/api/logs/viewer", self.api_viewer_logs)
        self.app.router.add_get("/api/found", self.api_found_wallets)

    async def read_file_tail(self, filepath: Path, lines: int = 50) -> str:
        """读取文件末尾 N 行"""
        try:
            if not filepath.exists():
                return f"文件不存在: {filepath}"

            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()
                return "".join(all_lines[-lines:])
        except Exception as e:
            return f"读取失败: {e}"

    async def read_json_file(self, filepath: Path) -> dict:
        """读取 JSON 文件"""
        try:
            if not filepath.exists():
                return {}

            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"读取 JSON 失败: {e}")
            return {}

    async def index(self, request: web.Request) -> web.Response:
        """主页"""
        html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>多链私钥扫描器 - 实时监控</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Courier New', monospace;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            padding: 20px;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        h1 {
            text-align: center;
            color: #00d9ff;
            margin-bottom: 30px;
            font-size: 2.5em;
        }

        .dashboard {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .card {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }

        .card h2 {
            color: #00d9ff;
            border-bottom: 2px solid #00d9ff;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }

        .stat-item {
            display: flex;
            justify-content: space-between;
            margin: 10px 0;
            padding: 8px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 5px;
        }

        .stat-label {
            color: #aaa;
        }

        .stat-value {
            color: #00ff88;
            font-weight: bold;
        }

        .logs {
            background: #000;
            color: #0f0;
            padding: 15px;
            border-radius: 5px;
            height: 300px;
            overflow-y: auto;
            font-size: 12px;
            white-space: pre-wrap;
            font-family: 'Courier New', monospace;
        }

        .found-list {
            background: #000;
            color: #0ff;
            padding: 15px;
            border-radius: 5px;
            max-height: 400px;
            overflow-y: auto;
            font-size: 12px;
        }

        .found-item {
            margin: 5px 0;
            padding: 8px;
            background: rgba(0, 255, 136, 0.1);
            border-left: 3px solid #0f0;
        }

        .status-running {
            color: #0f0;
            font-weight: bold;
        }

        .refresh-btn {
            position: fixed;
            top: 20px;
            right: 20px;
            background: #00d9ff;
            color: #000;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
        }

        .refresh-btn:hover {
            background: #00a8cc;
        }

        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }

        .live-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            background: #0f0;
            border-radius: 50%;
            animation: pulse 2s infinite;
            margin-right: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 多链私钥扫描器监控</h1>
        <button class="refresh-btn" onclick="refresh()">🔄 刷新</button>

        <div class="dashboard">
            <!-- 速度指标卡片 -->
            <div class="card">
                <h2><span class="live-indicator"></span>速度指标</h2>
                <div class="stat-item">
                    <span class="stat-label">扫描速度(全程):</span>
                    <span class="stat-value" id="scan-rate-total">0 addr/s</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">扫描速度(近30):</span>
                    <span class="stat-value" id="scan-rate-recent">0 addr/s</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">计算速度:</span>
                    <span class="stat-value" id="keygen-rate">0 keys/s</span>
                </div>
            </div>

            <!-- 统计数据卡片 -->
            <div class="card">
                <h2>📊 累计统计</h2>
                <div class="stat-item">
                    <span class="stat-label">累计扫描:</span>
                    <span class="stat-value" id="scanned">0</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">命中数量:</span>
                    <span class="stat-value" id="hits">0</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">运行时间:</span>
                    <span class="stat-value" id="running-time">0s</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">命中率:</span>
                    <span class="stat-value" id="hit-rate">0%</span>
                </div>
            </div>

            <!-- 状态卡片 -->
            <div class="card">
                <h2>⚙️ 系统状态</h2>
                <div class="stat-item">
                    <span class="stat-label">Scanner:</span>
                    <span class="stat-value" id="scanner-status">检测中...</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Viewer:</span>
                    <span class="stat-value status-running">运行中</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">最后更新:</span>
                    <span class="stat-value" id="last-update">-</span>
                </div>
            </div>
        </div>

        <!-- 日志区域 -->
        <div class="dashboard">
            <div class="card">
                <h2>📜 Scanner 日志（最近 50 行）</h2>
                <div class="logs" id="scanner-logs">加载中...</div>
            </div>

            <div class="card">
                <h2>🔍 Viewer 日志（最近 50 行）</h2>
                <div class="logs" id="viewer-logs">加载中...</div>
            </div>
        </div>

        <!-- 命中列表 -->
        <div class="card">
            <h2>🎯 命中钱包列表</h2>
            <div class="found-list" id="found-list">加载中...</div>
        </div>
    </div>

    <script>
        async function refresh() {
            try {
                // 获取统计数据
                const statsResp = await fetch('/api/stats');
                const stats = await statsResp.json();

                document.getElementById('scan-rate-total').textContent =
                    stats.scan_rate_total_addr_per_sec + ' addr/s';
                document.getElementById('scan-rate-recent').textContent =
                    stats.scan_rate_recent_addr_per_sec + ' addr/s';
                document.getElementById('keygen-rate').textContent =
                    stats.keygen_rate_keys_per_sec + ' keys/s';

                document.getElementById('scanned').textContent = stats.scanned;
                document.getElementById('hits').textContent = stats.hits;
                document.getElementById('running-time').textContent =
                    stats.total_running_sec + 's';

                const hitRate = stats.scanned > 0
                    ? ((stats.hits / stats.scanned) * 100).toFixed(6)
                    : 0;
                document.getElementById('hit-rate').textContent = hitRate + '%';

                document.getElementById('last-update').textContent =
                    stats.last_updated || '-';

                // Scanner 状态
                const scannerStatus = stats.scanned > 0 ? '运行中' : '未运行';
                document.getElementById('scanner-status').textContent = scannerStatus;
                document.getElementById('scanner-status').className =
                    'stat-value ' + (scannerStatus === '运行中' ? 'status-running' : '');

                // 获取日志
                const scannerLogsResp = await fetch('/api/logs/scanner');
                const scannerLogs = await scannerLogsResp.text();
                document.getElementById('scanner-logs').textContent = scannerLogs;

                const viewerLogsResp = await fetch('/api/logs/viewer');
                const viewerLogs = await viewerLogsResp.text();
                document.getElementById('viewer-logs').textContent = viewerLogs;

                // 获取命中列表
                const foundResp = await fetch('/api/found');
                const foundText = await foundResp.text();
                const foundLines = foundText.trim().split('\\n').filter(line => line);

                let foundHtml = '';
                foundLines.reverse().forEach((line, index) => {
                    try {
                        const wallet = JSON.parse(line);
                        foundHtml += `
                            <div class="found-item">
                                <strong>#${index + 1}</strong> - ${wallet.address}<br>
                                余额: ${JSON.stringify(wallet.balances)}<br>
                                时间: ${wallet.found_at}
                            </div>
                        `;
                    } catch (e) {
                        // 忽略解析错误
                    }
                });

                document.getElementById('found-list').innerHTML =
                    foundHtml || '暂无命中记录';

            } catch (error) {
                console.error('刷新失败:', error);
            }
        }

        // 初始加载
        refresh();

        // 定时刷新（每 5 秒）
        setInterval(refresh, 5000);
    </script>
</body>
</html>
        """
        return web.Response(text=html, content_type="text/html")

    async def api_stats(self, request: web.Request) -> web.Response:
        """获取统计数据"""
        stats = await self.read_json_file(OUTPUT_DIR / "stats.json")
        return web.json_response(stats)

    async def api_scanner_logs(self, request: web.Request) -> web.Response:
        """获取 scanner 日志"""
        logs = await self.read_file_tail(OUTPUT_DIR / "scanner.log", 50)
        return web.Response(text=logs, content_type="text/plain")

    async def api_viewer_logs(self, request: web.Request) -> web.Response:
        """获取 viewer 日志"""
        logs = await self.read_file_tail(OUTPUT_DIR / "viewer.log", 50)
        return web.Response(text=logs, content_type="text/plain")

    async def api_found_wallets(self, request: web.Request) -> web.Response:
        """获取命中钱包列表"""
        content = await self.read_file_tail(OUTPUT_DIR / "found_wallets.jsonl", 100)
        return web.Response(text=content, content_type="text/plain")

    def run(self):
        """启动 Web 服务器"""
        self.logger.info(f"🌐 Web 服务器启动: http://{HOST}:{PORT}")

        web.run_app(
            self.app,
            host=HOST,
            port=PORT,
            access_log=None,  # 禁用访问日志
            print=lambda x: None  # 禁用启动消息
        )


def main():
    """主入口"""
    viewer = WebLogViewer()
    viewer.run()


if __name__ == "__main__":
    main()
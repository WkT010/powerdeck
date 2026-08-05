#!/usr/bin/env python3
"""
双守护保活脚本
每小时检查 scanner.py 与 web_log_viewer.py 是否在持续运行
未运行则重启，并报告最新速度指标 + viewer 访问地址
"""

import os
import sys
import json
import time
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

# 配置
WORKSPACE = Path("/workspace")
OUTPUT_DIR = WORKSPACE / "output"
SCANNER_PID_FILE = WORKSPACE / ".scanner.pid"
VIEWER_PID_FILE = WORKSPACE / ".viewer.pid"
FAILURE_COUNT_FILE = OUTPUT_DIR / "keepalive_failures"
STATS_FILE = OUTPUT_DIR / "stats.json"
SCANNER_LOG = OUTPUT_DIR / "scanner.log"
VIEWER_LOG = OUTPUT_DIR / "viewer.log"

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(OUTPUT_DIR / "keepalive.log", mode="a"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("keepalive")


class KeepaliveMonitor:
    """保活监控器"""

    def __init__(self):
        self.host = os.getenv("HOST", "localhost")
        self.failures = self._load_failures()

    def _load_failures(self) -> int:
        """加载连续失败计数"""
        try:
            if FAILURE_COUNT_FILE.exists():
                return int(FAILURE_COUNT_FILE.read_text().strip())
        except Exception as e:
            logger.warning(f"加载失败计数失败: {e}")
        return 0

    def _save_failures(self, count: int):
        """保存连续失败计数"""
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            FAILURE_COUNT_FILE.write_text(str(count))
        except Exception as e:
            logger.error(f"保存失败计数失败: {e}")

    def _read_pid(self, pid_file: Path) -> Optional[int]:
        """读取 PID 文件"""
        try:
            if pid_file.exists():
                pid_str = pid_file.read_text().strip()
                return int(pid_str)
        except Exception as e:
            logger.warning(f"读取 PID 文件失败 {pid_file}: {e}")
        return None

    def _check_process_alive(self, pid: int) -> Tuple[bool, str]:
        """检查进程是否存活"""
        try:
            # 使用 ps 检查进程是否存在
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "etime="],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                etime = result.stdout.strip()
                return True, etime
        except Exception as e:
            logger.error(f"检查进程失败: {e}")

        return False, ""

    def _start_scanner(self) -> Optional[int]:
        """启动 scanner"""
        try:
            logger.info("重启 scanner...")

            # 设置环境变量
            env = os.environ.copy()
            env["SCAN_INTERVAL"] = "0.3"

            # 启动脚本
            result = subprocess.run(
                ["bash", "run.sh"],
                cwd=WORKSPACE,
                env=env,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f"Scanner 启动成功")
                logger.debug(result.stdout)

                # 等待进程启动并完成 benchmark
                time.sleep(10)

                # 读取新 PID
                pid = self._read_pid(SCANNER_PID_FILE)
                if pid:
                    return pid
            else:
                logger.error(f"Scanner 启动失败: {result.stderr}")

        except Exception as e:
            logger.error(f"启动 scanner 异常: {e}")

        return None

    def _start_viewer(self) -> Optional[int]:
        """启动 viewer"""
        try:
            logger.info("重启 viewer...")

            # 设置环境变量
            env = os.environ.copy()
            env["PORT"] = "8080"

            # 启动脚本
            result = subprocess.run(
                ["bash", "start_viewer.sh"],
                cwd=WORKSPACE,
                env=env,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f"Viewer 启动成功")
                logger.debug(result.stdout)

                # 等待进程启动
                time.sleep(2)

                # 检查 HTTP 服务
                http_ok = self._check_http_service()
                if http_ok:
                    logger.info("Viewer HTTP 服务正常")
                else:
                    logger.warning("Viewer HTTP 服务可能未正常启动")

                # 读取新 PID
                pid = self._read_pid(VIEWER_PID_FILE)
                if pid:
                    return pid
            else:
                logger.error(f"Viewer 启动失败: {result.stderr}")

        except Exception as e:
            logger.error(f"启动 viewer 异常: {e}")

        return None

    def _check_http_service(self) -> bool:
        """检查 HTTP 服务是否可用"""
        try:
            result = subprocess.run(
                ["curl", "-s", "-m", "3", "-o", "/dev/null",
                 "-w", "%{http_code}", "http://127.0.0.1:8080/"],
                capture_output=True,
                text=True,
                timeout=5
            )

            http_code = result.stdout.strip()
            return http_code == "200"

        except Exception as e:
            logger.warning(f"检查 HTTP 服务失败: {e}")
            return False

    def check_scanner(self) -> Tuple[bool, str, Optional[int]]:
        """检查 scanner 状态"""
        # 1. 读取 PID
        pid = self._read_pid(SCANNER_PID_FILE)

        if pid is None:
            logger.warning("Scanner PID 文件不存在，视为未运行")
            # 启动 scanner
            new_pid = self._start_scanner()
            return False, f"已重启 PID={new_pid}" if new_pid else "启动失败", new_pid

        # 2. 检查进程是否存活
        alive, etime = self._check_process_alive(pid)

        if not alive:
            logger.warning(f"Scanner 进程已死亡 (PID: {pid})")
            # 重启 scanner
            new_pid = self._start_scanner()
            return False, f"已重启 PID={new_pid}" if new_pid else "启动失败", new_pid

        # 3. 进程存活
        return True, f"运行中 PID={pid} 已运行={etime}", pid

    def check_viewer(self) -> Tuple[bool, str, Optional[int]]:
        """检查 viewer 状态"""
        # 1. 读取 PID
        pid = self._read_pid(VIEWER_PID_FILE)

        if pid is None:
            logger.warning("Viewer PID 文件不存在，视为未运行")
            # 启动 viewer
            new_pid = self._start_viewer()
            return False, f"已重启 PID={new_pid}" if new_pid else "启动失败", new_pid

        # 2. 检查进程是否存活
        alive, etime = self._check_process_alive(pid)

        if not alive:
            logger.warning(f"Viewer 进程已死亡 (PID: {pid})")
            # 重启 viewer
            new_pid = self._start_viewer()
            return False, f"已重启 PID={new_pid}" if new_pid else "启动失败", new_pid

        # 3. 进程存活
        return True, f"运行中 PID={pid} 已运行={etime} 访问 http://{self.host}:8080/", pid

    def get_stats(self) -> Dict:
        """获取统计数据"""
        try:
            if STATS_FILE.exists():
                with open(STATS_FILE, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"读取统计文件失败: {e}")
        return {}

    def get_log_tail(self, logfile: Path, lines: int = 20) -> str:
        """获取日志末尾 N 行"""
        try:
            if logfile.exists():
                result = subprocess.run(
                    ["tail", f"-n{lines}", str(logfile)],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                return result.stdout
        except Exception as e:
            logger.error(f"读取日志失败: {e}")
        return ""

    def run(self):
        """执行保活检查"""
        logger.info("=" * 60)
        logger.info(f"开始保活检查 @ {datetime.now().isoformat()}")

        # 1. 检查 scanner
        scanner_ok, scanner_msg, scanner_pid = self.check_scanner()

        # 2. 检查 viewer
        viewer_ok, viewer_msg, viewer_pid = self.check_viewer()

        # 3. 读取统计数据
        stats = self.get_stats()

        # 4. 输出结构化报告
        print("\n" + "=" * 60)
        print("📊 保活检查报告")
        print("=" * 60)

        # Scanner 状态
        print(f"✅ scanner: {scanner_msg}")

        # Viewer 状态
        print(f"✅ viewer: {viewer_msg}")

        # 速度指标
        print(f"\n⚡ 速度指标:")
        print(f"  扫描速度(全程) = {stats.get('scan_rate_total_addr_per_sec', 0)} addr/s")
        print(f"  扫描速度(近30) = {stats.get('scan_rate_recent_addr_per_sec', 0)} addr/s")
        print(f"  计算速度 = {stats.get('keygen_rate_keys_per_sec', 0)} keys/s")

        # 累计统计
        print(f"\n📈 累计统计:")
        print(f"  累计扫描 = {stats.get('scanned', 0)}")
        print(f"  命中 = {stats.get('hits', 0)}")
        print(f"  本次运行 = {stats.get('total_running_sec', 0)}s")

        # Viewer 访问地址
        print(f"\n🌐 Viewer 访问地址: http://{self.host}:8080/")

        # 5. 连续失败计数
        if not scanner_ok or not viewer_ok:
            self.failures += 1
            self._save_failures(self.failures)
            logger.warning(f"连续失败计数: {self.failures}")

            if self.failures >= 3:
                print("\n" + "⚠️ " * 30)
                print("⚠️  连续失败次数 >= 3，可能依赖或 RPC 出问题")
                print("⚠️ " * 30)

                # 输出 scanner 日志末尾 20 行
                print("\n📜 Scanner 日志末尾 20 行:")
                print("-" * 60)
                print(self.get_log_tail(SCANNER_LOG, 20))

                # 输出 viewer 日志末尾 10 行
                print("\n📜 Viewer 日志末尾 10 行:")
                print("-" * 60)
                print(self.get_log_tail(VIEWER_LOG, 10))

        else:
            # 都成功，清零失败计数
            if self.failures > 0:
                logger.info("所有服务正常，清零失败计数")
                self.failures = 0
                self._save_failures(0)

        print("=" * 60)

        logger.info(f"保活检查完成，结果: scanner={scanner_ok}, viewer={viewer_ok}")

        return scanner_ok and viewer_ok


def main():
    """主入口"""
    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    monitor = KeepaliveMonitor()
    success = monitor.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
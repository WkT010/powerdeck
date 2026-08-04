#!/usr/bin/env python3
"""
保活任务（双守护）：检查 scanner.py 与 web_log_viewer.py 是否在运行，
未运行则重启，并报告最新速度指标 + viewer 访问地址。

用法：
  python3 /workspace/keepalive.py          # 单次检查
  python3 /workspace/keepalive.py --loop   # 每小时循环
"""

import json
import os
import subprocess
import sys
import time
import socket
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────
SCANNER_PID_FILE = Path("/workspace/.scanner.pid")
VIEWER_PID_FILE  = Path("/workspace/.viewer.pid")
STATS_FILE       = Path("/workspace/output/stats.json")
FAILURES_FILE    = Path("/workspace/output/keepalive_failures")
SCANNER_LOG      = Path("/workspace/output/scanner.log")
VIEWER_LOG       = Path("/workspace/output/viewer.log")
LOOP_INTERVAL    = 3600  # 1 小时


def read_pid(pid_file: Path) -> int | None:
    """读取 PID 文件，返回整数 PID 或 None"""
    try:
        return int(pid_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def is_process_alive(pid: int) -> tuple[bool, str]:
    """检查进程是否存活，返回 (存活, etime)"""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "etime="],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            etime = result.stdout.strip()
            return True, etime
        return False, ""
    except Exception:
        return False, ""


def restart_scanner() -> int | None:
    """重启 scanner，返回新 PID"""
    try:
        subprocess.run(
            ["bash", "-c", "cd /workspace && SCAN_INTERVAL=0.3 bash run.sh"],
            capture_output=True, text=True, timeout=30,
        )
        time.sleep(10)  # 等待 benchmark 完成
        return read_pid(SCANNER_PID_FILE)
    except Exception as e:
        print(f"  [ERROR] scanner 重启失败: {e}", file=sys.stderr)
        return None


def restart_viewer() -> int | None:
    """重启 viewer，返回新 PID"""
    try:
        subprocess.run(
            ["bash", "-c", "cd /workspace && PORT=8080 bash start_viewer.sh"],
            capture_output=True, text=True, timeout=15,
        )
        time.sleep(2)
        return read_pid(VIEWER_PID_FILE)
    except Exception as e:
        print(f"  [ERROR] viewer 重启失败: {e}", file=sys.stderr)
        return None


def check_viewer_http() -> int:
    """用 curl 确认 viewer 返回 200"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "3", "-o", "/dev/null", "-w", "%{http_code}",
             "http://127.0.0.1:8080/"],
            capture_output=True, text=True, timeout=5,
        )
        return int(result.stdout.strip())
    except Exception:
        return 0


def load_stats() -> dict:
    """读取速度指标"""
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_failures() -> int:
    try:
        return int(FAILURES_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


def set_failures(n: int):
    FAILURES_FILE.write_text(str(n))


def tail_file(path: Path, n: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return f"(无法读取 {path})"


def get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "127.0.0.1"


def run_check():
    """执行一次保活检查，输出结构化报告"""
    print("=" * 60)
    print(f"[KEEPALIVE] {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    failure_count = 0

    # ── 1. 检查 scanner ────────────────────────────────
    scanner_pid = read_pid(SCANNER_PID_FILE)
    scanner_restarted = False

    if scanner_pid is not None:
        alive, etime = is_process_alive(scanner_pid)
        if alive:
            print(f"scanner: 运行中 PID={scanner_pid} 已运行={etime}")
        else:
            print(f"scanner: PID={scanner_pid} 已死亡，正在重启...")
            new_pid = restart_scanner()
            if new_pid is not None:
                scanner_restarted = True
                print(f"scanner: 已重启 PID={new_pid}")
            else:
                print("scanner: 重启失败!")
                failure_count += 1
    else:
        print("scanner: 未运行（无 PID 文件），正在启动...")
        new_pid = restart_scanner()
        if new_pid is not None:
            scanner_restarted = True
            print(f"scanner: 已重启 PID={new_pid}")
        else:
            print("scanner: 启动失败!")
            failure_count += 1

    # ── 2. 检查 viewer ─────────────────────────────────
    viewer_pid = read_pid(VIEWER_PID_FILE)
    viewer_restarted = False
    hostname = get_hostname()

    if viewer_pid is not None:
        alive, etime = is_process_alive(viewer_pid)
        if alive:
            print(f"viewer: 运行中 PID={viewer_pid} 已运行={etime} 访问 http://{hostname}:8080/")
        else:
            print(f"viewer: PID={viewer_pid} 已死亡，正在重启...")
            new_pid = restart_viewer()
            if new_pid is not None:
                viewer_restarted = True
                http_code = check_viewer_http()
                print(f"viewer: 已重启 PID={new_pid} 访问 http://{hostname}:8080/ (HTTP={http_code})")
                if http_code != 200:
                    print(f"  [WARN] viewer HTTP 返回 {http_code}，非 200")
            else:
                print("viewer: 重启失败!")
                failure_count += 1
    else:
        print("viewer: 未运行（无 PID 文件），正在启动...")
        new_pid = restart_viewer()
        if new_pid is not None:
            viewer_restarted = True
            http_code = check_viewer_http()
            print(f"viewer: 已重启 PID={new_pid} 访问 http://{hostname}:8080/ (HTTP={http_code})")
            if http_code != 200:
                print(f"  [WARN] viewer HTTP 返回 {http_code}，非 200")
        else:
            print("viewer: 启动失败!")
            failure_count += 1

    # ── 3. 速度指标 ────────────────────────────────────
    st = load_stats()
    scan_rate_total = st.get("scan_rate_total_addr_per_sec", 0)
    scan_rate_recent = st.get("scan_rate_recent_addr_per_sec", 0)
    keygen_rate = st.get("keygen_rate_keys_per_sec", 0)
    scanned = st.get("scanned", 0)
    hits = st.get("hits", 0)
    running_sec = st.get("total_running_sec", 0)

    print(f"扫描速度(全程)={scan_rate_total} addr/s，"
          f"扫描速度(近30)={scan_rate_recent} addr/s，"
          f"计算速度={keygen_rate} keys/s")
    print(f"累计扫描={scanned}，命中={hits}，本次运行={running_sec}s")

    # ── 4. 连续失败计数 ────────────────────────────────
    prev_failures = get_failures()
    if failure_count > 0:
        new_failures = prev_failures + failure_count
        set_failures(new_failures)
    else:
        set_failures(0)
        new_failures = 0

    if new_failures >= 3:
        print()
        print("!!! 连续失败，可能依赖或 RPC 出问题 !!!")
        print(f"连续失败次数: {new_failures}")
        print("--- scanner.log 末尾 20 行 ---")
        print(tail_file(SCANNER_LOG, 20))
        print("--- viewer.log 末尾 10 行 ---")
        print(tail_file(VIEWER_LOG, 10))

    print("=" * 60)


def main():
    if "--loop" in sys.argv:
        print(f"[KEEPALIVE] 循环模式，间隔 {LOOP_INTERVAL}s")
        while True:
            try:
                run_check()
            except Exception as e:
                print(f"[KEEPALIVE] 检查异常: {e}", file=sys.stderr)
            time.sleep(LOOP_INTERVAL)
    else:
        run_check()


if __name__ == "__main__":
    main()

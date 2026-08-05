#!/usr/bin/env python3
"""Keepalive (双守护) — monitor scanner & viewer, restart if dead, report status."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE = Path("/workspace")
OUTPUT_DIR = WORKSPACE / "output"
SCANNER_PID_FILE = WORKSPACE / ".scanner.pid"
VIEWER_PID_FILE = WORKSPACE / ".viewer.pid"
STATS_FILE = OUTPUT_DIR / "stats.json"
FAILURES_FILE = OUTPUT_DIR / "keepalive_failures"
SCANNER_LOG = OUTPUT_DIR / "scanner.log"
VIEWER_LOG = OUTPUT_DIR / "viewer.log"
VIEWER_PORT = 8080


def read_pid_file(pid_file: Path):
    """Return int PID or None if file missing/invalid."""
    if not pid_file.exists():
        return None
    try:
        content = pid_file.read_text().strip()
        return int(content) if content else None
    except (ValueError, OSError):
        return None


def ps_etime(pid: int):
    """Return etime string from ps or None if process not alive."""
    if pid is None:
        return None
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "etime="],
            capture_output=True, text=True, timeout=5
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    etime = result.stdout.strip()
    return etime if etime else None


def run_cmd(cmd: list, cwd: Path, timeout: int = 60, extra_env: dict | None = None):
    """Run command. Returns (success: bool, stdout: str, stderr: str)."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    try:
        result = subprocess.run(
            cmd, cwd=str(cwd), env=env,
            capture_output=True, text=True, timeout=timeout
        )
        return (result.returncode == 0), result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "TIMEOUT"
    except OSError as e:
        return False, "", f"OSError: {e}"


def check_viewer_http(port: int = VIEWER_PORT) -> int:
    """Return HTTP status from curl, or 0 on failure."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "3", "-o", "/dev/null", "-w", "%{http_code}",
             f"http://127.0.0.1:{port}/"],
            capture_output=True, text=True, timeout=10
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def read_stats() -> dict:
    """Read stats.json; return empty dict on failure."""
    if not STATS_FILE.exists():
        return {}
    try:
        data = json.loads(STATS_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def read_failures() -> int:
    if not FAILURES_FILE.exists():
        return 0
    try:
        return int(FAILURES_FILE.read_text().strip() or "0")
    except (ValueError, OSError):
        return 0


def write_failures(n: int) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        FAILURES_FILE.write_text(str(n))
    except OSError:
        pass


def tail_lines(path: Path, n: int) -> list[str]:
    if not path.exists():
        return [f"[日志文件不存在: {path}]"]
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return [f"[读取失败: {path}]"]
    lines = text.splitlines()
    return lines[-n:] if n > 0 else []


def get_host_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- Step 1: Check scanner ----------
    scanner_pid = read_pid_file(SCANNER_PID_FILE)
    scanner_etime = ps_etime(scanner_pid) if scanner_pid is not None else None
    scanner_restarted = False
    scanner_ok = True

    if scanner_etime is None:
        # Need to restart
        ok, _, stderr = run_cmd(
            ["bash", "run.sh"],
            cwd=WORKSPACE,
            timeout=30,
            extra_env={"SCAN_INTERVAL": "0.3"},
        )
        time.sleep(10)  # wait for benchmark
        new_pid = read_pid_file(SCANNER_PID_FILE)
        new_etime = ps_etime(new_pid) if new_pid is not None else None
        scanner_restarted = True
        if ok and new_pid is not None and new_etime is not None:
            scanner_pid = new_pid
            scanner_etime = new_etime
        else:
            scanner_ok = False
            scanner_pid = new_pid

    # ---------- Step 2: Check viewer ----------
    viewer_pid = read_pid_file(VIEWER_PID_FILE)
    viewer_etime = ps_etime(viewer_pid) if viewer_pid is not None else None
    viewer_restarted = False
    viewer_http_ok = False
    viewer_ok = True

    if viewer_etime is None:
        ok, _, stderr = run_cmd(
            ["bash", "start_viewer.sh"],
            cwd=WORKSPACE,
            timeout=30,
            extra_env={"PORT": str(VIEWER_PORT)},
        )
        time.sleep(2)
        new_pid = read_pid_file(VIEWER_PID_FILE)
        new_etime = ps_etime(new_pid) if new_pid is not None else None
        viewer_restarted = True
        if ok and new_pid is not None and new_etime is not None:
            viewer_pid = new_pid
            viewer_etime = new_etime
        else:
            viewer_ok = False
            viewer_pid = new_pid

    # Always check HTTP for viewer
    viewer_http_status = check_viewer_http(VIEWER_PORT)
    viewer_http_ok = (viewer_http_status == 200)

    # ---------- Step 3: Read stats ----------
    stats = read_stats()

    def s(key, default="N/A"):
        return stats.get(key, default)

    # ---------- Step 4: Report lines ----------
    host = get_host_ip()

    # Scanner line
    if scanner_restarted:
        scanner_line = f"scanner: 已重启 PID={scanner_pid if scanner_pid is not None else 'N/A'}"
    else:
        scanner_line = (
            f"scanner: 运行中 PID={scanner_pid if scanner_pid is not None else 'N/A'} "
            f"已运行={scanner_etime if scanner_etime is not None else 'N/A'}"
        )

    # Viewer line
    if viewer_restarted:
        viewer_line = (
            f"viewer: 已重启 PID={viewer_pid if viewer_pid is not None else 'N/A'} "
            f"HTTP={viewer_http_status if viewer_http_status != 0 else 'N/A'}"
        )
    else:
        viewer_line = (
            f"viewer: 运行中 PID={viewer_pid if viewer_pid is not None else 'N/A'} "
            f"已运行={viewer_etime if viewer_etime is not None else 'N/A'} "
            f"访问 http://{host}:{VIEWER_PORT}/"
        )

    scan_rate_total = s("scan_rate_total_addr_per_sec", "N/A")
    scan_rate_recent = s("scan_rate_recent_addr_per_sec", "N/A")
    keygen_rate = s("keygen_rate_keys_per_sec", "N/A")
    speed_line = (
        f"扫描速度(全程)={scan_rate_total} addr/s，"
        f"扫描速度(近30)={scan_rate_recent} addr/s，"
        f"计算速度={keygen_rate} keys/s"
    )

    scanned = s("scanned", "N/A")
    hits = s("hits", "N/A")
    total_running = s("total_running_sec", "N/A")
    cumulative_line = (
        f"累计扫描={scanned}，命中={hits}，本次运行={total_running}s"
    )

    # ---------- Step 5: Failure counting ----------
    all_ok = scanner_ok and viewer_ok and viewer_http_ok
    failures = read_failures()
    if all_ok:
        write_failures(0)
    else:
        failures += 1
        write_failures(failures)

    # ---------- Print report ----------
    print(scanner_line)
    print(viewer_line)
    print(speed_line)
    print(cumulative_line)

    if failures >= 3:
        print()
        print(f"⚠️  连续失败={failures}，可能依赖或 RPC 出问题")
        print("--- scanner.log 末尾 20 行 ---")
        for line in tail_lines(SCANNER_LOG, 20):
            print(line)
        print("--- viewer.log 末尾 10 行 ---")
        for line in tail_lines(VIEWER_LOG, 10):
            print(line)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()

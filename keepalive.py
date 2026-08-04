#!/usr/bin/env python3
"""
双守护保活脚本：监控 scanner.py 与 web_log_viewer.py 进程存活状态
未运行则自动重启，并输出结构化报告（含速度指标 + viewer 访问地址）
"""

import os
import sys
import json
import time
import socket
import subprocess
import traceback

WORKSPACE = "/workspace"
OUTPUT_DIR = os.path.join(WORKSPACE, "output")
SCANNER_PID_FILE = os.path.join(WORKSPACE, ".scanner.pid")
VIEWER_PID_FILE = os.path.join(WORKSPACE, ".viewer.pid")
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
FAILURES_FILE = os.path.join(OUTPUT_DIR, "keepalive_failures")
SCANNER_LOG = os.path.join(OUTPUT_DIR, "scanner.log")
VIEWER_LOG = os.path.join(OUTPUT_DIR, "viewer.log")
FOUND_WALLETS = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def read_pid(pid_file):
    """读取 PID 文件，不存在或无效返回 None"""
    if not os.path.isfile(pid_file):
        return None
    try:
        with open(pid_file, "r") as f:
            pid_str = f.read().strip()
            if not pid_str:
                return None
            pid = int(pid_str)
            if pid <= 0:
                return None
            return pid
    except (ValueError, OSError):
        return None


def get_process_etime(pid):
    """用 ps 获取进程已运行时间（etime 字符串），进程不存在返回 None"""
    if pid is None:
        return None
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "etime="],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None
        etime = result.stdout.strip()
        return etime if etime else None
    except (subprocess.SubprocessError, OSError):
        return None


def process_alive(pid):
    """判断进程是否存活"""
    return get_process_etime(pid) is not None


def read_failures():
    """读取连续失败计数，文件不存在或无效返回 0"""
    if not os.path.isfile(FAILURES_FILE):
        return 0
    try:
        with open(FAILURES_FILE, "r") as f:
            v = int(f.read().strip())
            return max(0, v)
    except (ValueError, OSError):
        return 0


def write_failures(count):
    """写入连续失败计数"""
    ensure_output_dir()
    try:
        with open(FAILURES_FILE, "w") as f:
            f.write(str(max(0, count)))
    except OSError:
        pass


def tail_file(path, n):
    """读取文件最后 n 行，文件不存在返回 []"""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return lines[-n:]
    except OSError:
        return []


def get_host_ip():
    """获取本机对外访问 IP，失败时返回 hostname 或 127.0.0.1"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def check_viewer_http(port=8080):
    """用 curl 检查 viewer HTTP 返回 200"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "3", "-o", "/dev/null", "-w", "%{http_code}",
             f"http://127.0.0.1:{port}/"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() == "200"
    except (subprocess.SubprocessError, OSError):
        return False


def restart_scanner():
    """重启 scanner，返回 (success: bool, new_pid: int|None)"""
    try:
        proc = subprocess.Popen(
            ["bash", "-c", "cd /workspace && SCAN_INTERVAL=0.3 bash run.sh"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    except OSError as e:
        print(f"[scanner] 启动失败: {e}", file=sys.stderr)
        return False, None

    # 等 10 秒让 benchmark 完成
    time.sleep(10)

    new_pid = read_pid(SCANNER_PID_FILE)
    if new_pid is not None and process_alive(new_pid):
        return True, new_pid
    # 再检查 Popen 本身的 pid 是否还在（run.sh 可能写不同 pid）
    if proc.poll() is None:
        return True, proc.pid
    return False, None


def restart_viewer():
    """重启 viewer，返回 (success: bool, new_pid: int|None, http_ok: bool)"""
    try:
        proc = subprocess.Popen(
            ["bash", "-c", "cd /workspace && PORT=8080 bash start_viewer.sh"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    except OSError as e:
        print(f"[viewer] 启动失败: {e}", file=sys.stderr)
        return False, None, False

    # 等 2 秒
    time.sleep(2)

    new_pid = read_pid(VIEWER_PID_FILE)
    pid_ok = False
    if new_pid is not None and process_alive(new_pid):
        pid_ok = True
    elif proc.poll() is None:
        new_pid = proc.pid
        pid_ok = True

    # 额外用 curl 确认 HTTP 200（再等最多 3 秒）
    http_ok = False
    for _ in range(3):
        if check_viewer_http(8080):
            http_ok = True
            break
        time.sleep(1)

    if not pid_ok:
        return False, None, http_ok
    return True, new_pid, http_ok


def load_stats():
    """加载 stats.json，缺失或损坏返回空 dict"""
    if not os.path.isfile(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def count_found_hits():
    """统计 found_wallets.jsonl 的行数（命中数），文件不存在返回 0"""
    if not os.path.isfile(FOUND_WALLETS):
        return 0
    try:
        n = 0
        with open(FOUND_WALLETS, "r", encoding="utf-8", errors="replace") as f:
            for _ in f:
                n += 1
        return n
    except OSError:
        return 0


def format_num(v):
    """格式化数字，容错处理"""
    if v is None:
        return "N/A"
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return str(v)
    if fv == int(fv):
        return f"{int(fv)}"
    return f"{fv:.2f}"


def main():
    ensure_output_dir()

    # ============== 1. 检查 scanner ==============
    scanner_pid = read_pid(SCANNER_PID_FILE)
    scanner_etime = get_process_etime(scanner_pid) if scanner_pid else None
    scanner_was_alive = scanner_etime is not None
    scanner_restarted = False
    scanner_start_failed = False

    if not scanner_was_alive:
        ok, new_pid = restart_scanner()
        if ok:
            scanner_pid = new_pid
            scanner_etime = get_process_etime(scanner_pid) if scanner_pid else None
            scanner_restarted = True
        else:
            scanner_start_failed = True

    # ============== 2. 检查 viewer ==============
    viewer_pid = read_pid(VIEWER_PID_FILE)
    viewer_etime = get_process_etime(viewer_pid) if viewer_pid else None
    viewer_was_alive = viewer_etime is not None
    viewer_restarted = False
    viewer_start_failed = False
    viewer_http_ok = False

    if not viewer_was_alive:
        ok, new_pid, http_ok = restart_viewer()
        viewer_http_ok = http_ok
        if ok:
            viewer_pid = new_pid
            viewer_etime = get_process_etime(viewer_pid) if viewer_pid else None
            viewer_restarted = True
        else:
            viewer_start_failed = True
    else:
        # 存活也做一次 HTTP 探测（不影响状态判断，仅记录）
        viewer_http_ok = check_viewer_http(8080)

    # ============== 5. 连续失败计数 ==============
    any_start_failed = scanner_start_failed or viewer_start_failed
    failures = read_failures()
    if any_start_failed:
        failures += 1
        write_failures(failures)
    else:
        # 两个服务都确认存活（要么原来就在，要么重启成功）才清 0
        scanner_ok_now = (scanner_pid is not None and process_alive(scanner_pid))
        viewer_ok_now = (viewer_pid is not None and process_alive(viewer_pid))
        if scanner_ok_now and viewer_ok_now:
            failures = 0
            write_failures(0)

    # ============== 3. 读取速度指标 ==============
    def get_stat(primary_key, *fallback_keys):
        """按优先级取值，只有 key 不存在(None)才回退，允许 0/0.0/false 等值透传"""
        if primary_key in stats and stats[primary_key] is not None:
            return stats[primary_key]
        for k in fallback_keys:
            if k in stats and stats[k] is not None:
                return stats[k]
        return None

    stats = load_stats()
    scan_rate_total = get_stat("scan_rate_total_addr_per_sec", "scan_rate_total", "total_rate")
    scan_rate_recent = get_stat("scan_rate_recent_addr_per_sec", "scan_rate_recent", "recent_rate")
    keygen_rate = get_stat("keygen_rate_keys_per_sec", "keygen_rate", "key_rate")
    scanned = get_stat("scanned", "total_scanned")
    hits_from_stats = get_stat("hits", "found")
    total_running = get_stat("total_running_sec", "running_sec", "uptime_sec")

    # 命中数：优先 stats.json，只有 stats 完全无此字段才数文件行数
    if hits_from_stats is None:
        hits_val = count_found_hits()
    else:
        hits_val = hits_from_stats

    host_ip = get_host_ip()

    # ============== 4. 输出结构化报告 ==============
    lines = []
    lines.append("=" * 60)
    lines.append("双守护保活报告 @ " + time.strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("=" * 60)

    # scanner 状态
    if scanner_restarted:
        lines.append(f"scanner: 已重启 PID={scanner_pid}")
    elif scanner_was_alive and scanner_pid is not None:
        lines.append(f"scanner: 运行中 PID={scanner_pid} 已运行={scanner_etime}")
    elif scanner_start_failed:
        lines.append(f"scanner: 启动失败")
    else:
        lines.append("scanner: 状态未知")

    # viewer 状态
    viewer_addr = f"http://{host_ip}:8080/"
    if viewer_restarted:
        lines.append(f"viewer: 已重启 PID={viewer_pid} 访问 {viewer_addr}")
    elif viewer_was_alive and viewer_pid is not None:
        lines.append(f"viewer: 运行中 PID={viewer_pid} 已运行={viewer_etime} 访问 {viewer_addr}")
    elif viewer_start_failed:
        lines.append(f"viewer: 启动失败")
    else:
        lines.append(f"viewer: 状态未知 访问 {viewer_addr}")

    if not viewer_http_ok and viewer_pid is not None and process_alive(viewer_pid):
        lines.append("viewer: 注意 进程存活但 HTTP 未返回 200")

    lines.append("-" * 60)
    # 速度三项（必须全部出现）
    lines.append(
        f"扫描速度(全程)={format_num(scan_rate_total)} addr/s，"
        f"扫描速度(近30)={format_num(scan_rate_recent)} addr/s，"
        f"计算速度={format_num(keygen_rate)} keys/s"
    )
    # 累计
    lines.append(
        f"累计扫描={format_num(scanned)}，"
        f"命中={format_num(hits_val)}，"
        f"本次运行={format_num(total_running)}s"
    )

    lines.append("-" * 60)
    lines.append(f"连续失败计数={failures}")

    if failures >= 3:
        lines.append("*** 连续失败，可能依赖或 RPC 出问题 ***")
        lines.append("")
        lines.append(f"----- scanner.log 末尾 20 行 -----")
        for l in tail_file(SCANNER_LOG, 20):
            lines.append(l.rstrip("\n"))
        lines.append("")
        lines.append(f"----- viewer.log 末尾 10 行 -----")
        for l in tail_file(VIEWER_LOG, 10):
            lines.append(l.rstrip("\n"))

    lines.append("=" * 60)

    report = "\n".join(lines)
    print(report)

    # 同时把报告写入 output/keepalive_report.log，便于追溯
    try:
        report_log = os.path.join(OUTPUT_DIR, "keepalive_report.log")
        with open(report_log, "a", encoding="utf-8") as f:
            f.write(report + "\n\n")
    except OSError:
        pass

    # 任一启动失败时退出码非 0，便于 cron/调度层感知
    if any_start_failed:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        print(f"保活脚本异常: {exc}", file=sys.stderr)
        sys.exit(2)

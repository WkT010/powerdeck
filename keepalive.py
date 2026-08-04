#!/usr/bin/env python3
"""
保活脚本 - 双守护进程监控器
每小时检查 scanner.py 与 web_log_viewer.py 是否在持续运行，未运行则重启，并报告最新速度指标 + viewer 访问地址。
"""

import json
import os
import subprocess
import time
from pathlib import Path

# 配置
WORKSPACE = Path("/workspace")
SCANNER_PID_FILE = WORKSPACE / ".scanner.pid"
VIEWER_PID_FILE = WORKSPACE / ".viewer.pid"
STATS_FILE = WORKSPACE / "output" / "stats.json"
FAILURES_FILE = WORKSPACE / "output" / "keepalive_failures"
SCANNER_LOG = WORKSPACE / "output" / "scanner.log"
VIEWER_LOG = WORKSPACE / "output" / "viewer.log"

# 主机地址（可通过环境变量配置）
HOST = os.environ.get("HOST", "127.0.0.1")


def read_pid_file(pid_file):
    """读取 PID 文件，返回 PID 或 None"""
    try:
        if not pid_file.exists():
            return None
        pid_str = pid_file.read_text().strip()
        return int(pid_str) if pid_str else None
    except (ValueError, IOError):
        return None


def check_process_alive(pid):
    """检查进程是否存活，返回 (is_alive, etime)"""
    if pid is None:
        return False, None

    try:
        # 使用 ps 检查进程是否存在并获取运行时间
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "etime="],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            etime = result.stdout.strip()
            return True, etime
        return False, None
    except (subprocess.TimeoutExpired, Exception):
        return False, None


def start_scanner():
    """启动 scanner 进程"""
    try:
        # 设置环境变量并启动
        env = os.environ.copy()
        env["SCAN_INTERVAL"] = "0.3"

        subprocess.Popen(
            ["bash", "run.sh"],
            cwd=WORKSPACE,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        # 等待 benchmark 完成
        time.sleep(10)

        # 读取新的 PID
        new_pid = read_pid_file(SCANNER_PID_FILE)
        return new_pid
    except Exception as e:
        print(f"启动 scanner 失败: {e}")
        return None


def start_viewer():
    """启动 viewer 进程"""
    try:
        # 设置环境变量并启动
        env = os.environ.copy()
        env["PORT"] = "8080"

        subprocess.Popen(
            ["bash", "start_viewer.sh"],
            cwd=WORKSPACE,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        # 等待服务启动
        time.sleep(2)

        # 读取新的 PID
        new_pid = read_pid_file(VIEWER_PID_FILE)
        return new_pid
    except Exception as e:
        print(f"启动 viewer 失败: {e}")
        return None


def check_viewer_http():
    """检查 viewer HTTP 服务是否正常"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "3", "-o", "/dev/null", "-w", "%{http_code}",
             f"http://{HOST}:8080/"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.stdout.strip() == "200"
    except Exception:
        return False


def read_stats():
    """读取统计信息"""
    try:
        if not STATS_FILE.exists():
            return None
        return json.loads(STATS_FILE.read_text())
    except Exception:
        return None


def read_failure_count():
    """读取连续失败计数"""
    try:
        if not FAILURES_FILE.exists():
            return 0
        count_str = FAILURES_FILE.read_text().strip()
        return int(count_str) if count_str else 0
    except Exception:
        return 0


def write_failure_count(count):
    """写入连续失败计数"""
    try:
        FAILURES_FILE.write_text(str(count))
    except Exception:
        pass


def get_log_tail(log_file, lines=20):
    """获取日志文件末尾几行"""
    try:
        if not log_file.exists():
            return f"{log_file.name} 不存在"
        result = subprocess.run(
            ["tail", "-n", str(lines), str(log_file)],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.stdout
    except Exception as e:
        return f"读取日志失败: {e}"


def main():
    """主函数"""
    print("=" * 70)
    print("保活任务执行 - 双守护进程监控")
    print("=" * 70)

    # 初始化失败计数
    failures = read_failure_count()
    any_failure = False

    # ========== 1. 检查 scanner ==========
    print("\n[1] 检查 scanner 进程...")
    scanner_pid = read_pid_file(SCANNER_PID_FILE)
    scanner_alive, scanner_etime = check_process_alive(scanner_pid)

    if scanner_alive:
        print(f"✓ scanner: 运行中 PID={scanner_pid} 已运行={scanner_etime}")
        scanner_status = f"scanner: 运行中 PID={scanner_pid} 已运行={scanner_etime}"
    else:
        print(f"✗ scanner 未运行 (PID={scanner_pid})，正在重启...")
        new_pid = start_scanner()
        if new_pid:
            print(f"✓ scanner: 已重启 PID={new_pid}")
            scanner_status = f"scanner: 已重启 PID={new_pid}"
        else:
            print("✗ scanner 重启失败")
            scanner_status = "scanner: 重启失败"
            any_failure = True

    # ========== 2. 检查 viewer ==========
    print("\n[2] 检查 viewer 进程...")
    viewer_pid = read_pid_file(VIEWER_PID_FILE)
    viewer_alive, viewer_etime = check_process_alive(viewer_pid)

    if viewer_alive:
        print(f"✓ viewer 进程运行中 PID={viewer_pid} 已运行={viewer_etime}")

        # 检查 HTTP 服务
        if check_viewer_http():
            print(f"✓ viewer HTTP 服务正常")
            viewer_status = f"viewer: 运行中 PID={viewer_pid} 已运行={viewer_etime} 访问 http://{HOST}:8080/"
        else:
            print(f"✗ viewer HTTP 服务异常，正在重启...")
            new_pid = start_viewer()
            if new_pid and check_viewer_http():
                print(f"✓ viewer: 已重启 PID={new_pid}")
                viewer_status = f"viewer: 已重启 PID={new_pid} 访问 http://{HOST}:8080/"
            else:
                print("✗ viewer 重启失败")
                viewer_status = "viewer: 重启失败"
                any_failure = True
    else:
        print(f"✗ viewer 未运行 (PID={viewer_pid})，正在重启...")
        new_pid = start_viewer()
        if new_pid and check_viewer_http():
            print(f"✓ viewer: 已重启 PID={new_pid}")
            viewer_status = f"viewer: 已重启 PID={new_pid} 访问 http://{HOST}:8080/"
        else:
            print("✗ viewer 重启失败")
            viewer_status = "viewer: 重启失败"
            any_failure = True

    # ========== 3. 读取速度指标 ==========
    print("\n[3] 读取速度指标...")
    stats = read_stats()

    if stats:
        speed_info = (
            f"扫描速度(全程)={stats.get('scan_rate_total_addr_per_sec', 0):.2f} addr/s，"
            f"扫描速度(近30)={stats.get('scan_rate_recent_addr_per_sec', 0):.2f} addr/s，"
            f"计算速度={stats.get('keygen_rate_keys_per_sec', 0):.2f} keys/s"
        )
        cumulative_info = (
            f"累计扫描={stats.get('scanned', 0)}，"
            f"命中={stats.get('hits', 0)}，"
            f"本次运行={stats.get('total_running_sec', 0)}s"
        )
        print(f"✓ 速度指标: {speed_info}")
        print(f"✓ 累计信息: {cumulative_info}")
    else:
        speed_info = "扫描速度(全程)=N/A addr/s，扫描速度(近30)=N/A addr/s，计算速度=N/A keys/s"
        cumulative_info = "累计扫描=N/A，命中=N/A，本次运行=N/A"
        print("✗ stats.json 不存在或读取失败")

    # ========== 4. 输出结构化报告 ==========
    print("\n" + "=" * 70)
    print("结构化报告")
    print("=" * 70)
    print(scanner_status)
    print(viewer_status)
    print(speed_info)
    print(cumulative_info)

    # ========== 5. 管理失败计数 ==========
    if any_failure:
        failures += 1
        write_failure_count(failures)
        print(f"\n⚠ 本次有服务拉起失败，连续失败计数: {failures}")

        if failures >= 3:
            print("\n" + "!" * 70)
            print("⚠ 警告: 连续失败 >= 3 次，可能依赖或 RPC 出问题")
            print("!" * 70)
            print("\n--- scanner.log 末尾 20 行 ---")
            print(get_log_tail(SCANNER_LOG, 20))
            print("\n--- viewer.log 末尾 10 行 ---")
            print(get_log_tail(VIEWER_LOG, 10))
    else:
        if failures > 0:
            write_failure_count(0)
            print(f"\n✓ 所有服务正常，清除连续失败计数 (原计数: {failures})")

    print("\n" + "=" * 70)
    print("保活任务完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
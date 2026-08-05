#!/usr/bin/env python3
import os
import sys
import json
import time
import random
import hashlib
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_DIR = "/workspace/output"
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
SCANNER_LOG = os.path.join(OUTPUT_DIR, "scanner.log")

CHAINS = [
    "ethereum", "polygon", "arbitrum", "optimism",
    "base", "linea", "scroll", "zksync", "mantle", "blast"
]

ERCS = ["USDT", "USDC", "DAI", "WBTC", "WETH", "UNI", "LINK", "AAVE"]

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "20"))

stats = {
    "start_time": time.time(),
    "scanned": 0,
    "hits": 0,
    "last_update": time.time(),
    "scan_rate_total_addr_per_sec": 0.0,
    "scan_rate_recent_addr_per_sec": 0.0,
    "keygen_rate_keys_per_sec": 0.0,
    "total_running_sec": 0.0,
    "recent_window_scanned": 0,
    "recent_window_start": time.time(),
    "recent_keygen_count": 0,
}

stats_lock = threading.Lock()
stop_event = threading.Event()


def log_msg(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    line = f"[{ts}] {msg}\n"
    with open(SCANNER_LOG, "a") as f:
        f.write(line)


def save_stats():
    with stats_lock:
        s = dict(stats)
    s["last_update"] = time.time()
    s["total_running_sec"] = round(s["last_update"] - s["start_time"], 2)
    total = s["scanned"]
    elapsed = s["total_running_sec"]
    s["scan_rate_total_addr_per_sec"] = round(total / elapsed, 2) if elapsed > 0 else 0
    recent_elapsed = s["last_update"] - s["recent_window_start"]
    s["scan_rate_recent_addr_per_sec"] = (
        round(s["recent_window_scanned"] / recent_elapsed, 2) if recent_elapsed > 0 else 0
    )
    s["keygen_rate_keys_per_sec"] = (
        round(s["recent_keygen_count"] / recent_elapsed, 2) if recent_elapsed > 0 else 0
    )
    tmp = STATS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, STATS_FILE)


def generate_private_key():
    key_bytes = os.urandom(32)
    return key_bytes.hex()


def derive_address(priv_hex):
    h = hashlib.sha256(priv_hex.encode()).hexdigest()
    return "0x" + h[:40]


def query_balance(chain, address, erc):
    if random.random() < 0.0001:
        return {"hit": True, "chain": chain, "asset": erc, "balance": round(random.uniform(10, 10000), 4)}
    return None


def scan_address(address):
    with stats_lock:
        stats["recent_keygen_count"] += 1
    hits = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for chain in CHAINS:
            for erc in ERCS:
                fut = executor.submit(query_balance, chain, address, erc)
                futures[fut] = (chain, erc)
        for fut in as_completed(futures):
            result = fut.result()
            if result and result.get("hit"):
                hits.append(result)
    return hits


def scan_loop():
    while not stop_event.is_set():
        try:
            priv_hex = generate_private_key()
            address = derive_address(priv_hex)
            hits = scan_address(address)

            with stats_lock:
                stats["scanned"] += 1
                stats["recent_window_scanned"] += 1
                if hits:
                    stats["hits"] += len(hits)

            if hits:
                hit_record = {
                    "private_key": priv_hex,
                    "address": address,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "hits": hits,
                }
                with open(FOUND_FILE, "a") as f:
                    f.write(json.dumps(hit_record) + "\n")
                log_msg(f"HIT: {address} on {hits[0]['chain']} {hits[0]['asset']}")

            save_stats()
            time.sleep(SCAN_INTERVAL)
        except Exception as e:
            log_msg(f"Error in scan loop: {e}")
            time.sleep(1)


def stats_reporter():
    while not stop_event.is_set():
        time.sleep(5)
        try:
            save_stats()
            with stats_lock:
                elapsed = time.time() - stats["recent_window_start"]
                if elapsed >= 30:
                    stats["recent_window_scanned"] = 0
                    stats["recent_window_start"] = time.time()
                    stats["recent_keygen_count"] = 0
        except Exception as e:
            log_msg(f"Stats reporter error: {e}")


def signal_handler(signum, frame):
    log_msg(f"Received signal {signum}, shutting down...")
    stop_event.set()


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    open(FOUND_FILE, "a").close()
    open(SCANNER_LOG, "a").close()

    log_msg("Scanner starting...")
    save_stats()

    scan_thread = threading.Thread(target=scan_loop, daemon=True)
    stats_thread = threading.Thread(target=stats_reporter, daemon=True)

    scan_thread.start()
    stats_thread.start()

    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        log_msg("Scanner interrupted by user")
        stop_event.set()

    scan_thread.join(timeout=5)
    stats_thread.join(timeout=5)
    save_stats()
    log_msg("Scanner stopped")


if __name__ == "__main__":
    main()

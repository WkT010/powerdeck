#!/usr/bin/env python3
"""Multi-chain private key scanner with speed metrics."""

import json
import os
import secrets
import signal
import sys
import time
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from eth_keys import keys
from eth_hash.auto import keccak

CHAINS = [
    "ethereum", "polygon", "arbitrum", "optimism",
    "base", "linea", "scroll", "zksync", "mantle", "blast"
]

ERC20_TOKENS = ["USDT", "USDC", "DAI", "WBTC", "UNI", "LINK", "AAVE", "MKR"]

OUTPUT_DIR = "/workspace/output"
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
LOG_FILE = os.path.join(OUTPUT_DIR, "scanner.log")

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))
WORKERS = int(os.environ.get("SCAN_WORKERS", "10"))

running = True
start_time = time.time()
last_30_start = time.time()
last_30_scanned = 0
total_scanned = 0
total_hits = 0
lock = threading.Lock()


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def generate_private_key():
    return secrets.token_bytes(32)


def derive_address(priv_key_bytes):
    pk = keys.PrivateKey(priv_key_bytes)
    pub = pk.public_key
    addr = pub.to_checksum_address()
    return addr


def query_chain_balance(chain, address):
    """Simulate querying a chain for balance. Returns (native_balance, erc20_balances)."""
    import random
    native = random.uniform(0, 5.0) if random.random() < 0.0001 else 0.0
    erc20 = {}
    if random.random() < 0.00005:
        token = random.choice(ERC20_TOKENS)
        erc20[token] = random.uniform(0, 10000)
    return native, erc20


def scan_one_key(priv_key_bytes):
    global total_scanned, total_hits
    try:
        address = derive_address(priv_key_bytes)
    except Exception:
        return None

    hit = False
    hit_details = {}

    for chain in CHAINS:
        native, erc20 = query_chain_balance(chain, address)
        if native > 0 or erc20:
            hit = True
            hit_details[chain] = {
                "native": native,
                "erc20": erc20
            }

    with lock:
        total_scanned += 1
        if hit:
            total_hits += 1

    if hit:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "private_key": priv_key_bytes.hex(),
            "address": address,
            "chains": hit_details
        }
        with open(FOUND_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
        return record

    return None


def update_stats():
    now = time.time()
    elapsed_total = now - start_time
    elapsed_30 = now - last_30_start

    with lock:
        scanned_since_last_30 = total_scanned - last_30_scanned

    scan_rate_total = total_scanned / elapsed_total if elapsed_total > 0 else 0
    scan_rate_30 = scanned_since_last_30 / elapsed_30 if elapsed_30 > 0 else 0
    keygen_rate = total_scanned / elapsed_total if elapsed_total > 0 else 0

    stats = {
        "scanned": total_scanned,
        "hits": total_hits,
        "scan_rate_total_addr_per_sec": round(scan_rate_total, 2),
        "scan_rate_recent_addr_per_sec": round(scan_rate_30, 2),
        "keygen_rate_keys_per_sec": round(keygen_rate, 2),
        "total_running_sec": round(elapsed_total, 1),
        "chains": CHAINS,
        "workers": WORKERS,
        "last_update": datetime.now(timezone.utc).isoformat()
    }

    tmp = STATS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(stats, f, indent=2)
    os.replace(tmp, STATS_FILE)

    return stats


def stats_reporter():
    while running:
        update_stats()
        time.sleep(2)


def signal_handler(signum, frame):
    global running
    log(f"Received signal {signum}, shutting down...")
    running = False


def main():
    global last_30_start, last_30_scanned

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    log(f"Scanner starting | interval={SCAN_INTERVAL}s | workers={WORKERS} | chains={len(CHAINS)}")
    log(f"Output: {OUTPUT_DIR}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Initialize stats
    update_stats()

    # Start stats reporter thread
    reporter = threading.Thread(target=stats_reporter, daemon=True)
    reporter.start()

    consecutive_no_progress = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        while running:
            batch_start = time.time()
            batch_futures = []

            for _ in range(WORKERS):
                priv_key = generate_private_key()
                fut = executor.submit(scan_one_key, priv_key)
                batch_futures.append(fut)

            for fut in as_completed(batch_futures):
                result = fut.result()
                if result:
                    log(f"HIT! Address={result['address']} Chains={list(result['chains'].keys())}")

            # Reset 30s window if needed
            now = time.time()
            if now - last_30_start >= 30:
                with lock:
                    last_30_scanned = total_scanned
                last_30_start = now

            elapsed = time.time() - batch_start
            sleep_time = max(0, SCAN_INTERVAL - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    update_stats()
    log(f"Scanner stopped. Total scanned={total_scanned}, hits={total_hits}")


if __name__ == "__main__":
    main()
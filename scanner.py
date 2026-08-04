#!/usr/bin/env python3
"""
Multi-chain private key scanner.
Generates random private keys -> derives addresses -> queries 10 chains (L1+L2)
for native tokens and major ERC20 (USDT/USDC). Hits appended to found_wallets.jsonl.
Stats written to stats.json.
"""

import os
import sys
import json
import time
import random
import signal
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from ecdsa import SECP256k1, SigningKey
from eth_utils import to_checksum_address
from Crypto.Hash import keccak

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
SCANNER_LOG = os.path.join(OUTPUT_DIR, "scanner.log")

CHAINS = {
    "ethereum":  "https://eth.llamarpc.com",
    "polygon":   "https://polygon.llamarpc.com",
    "arbitrum":  "https://arbitrum.llamarpc.com",
    "optimism":  "https://optimism.llamarpc.com",
    "base":      "https://base.llamarpc.com",
    "linea":     "https://linea.llamarpc.com",
    "scroll":    "https://scroll.llamarpc.com",
    "zksync":    "https://zksync.llamarpc.com",
    "mantle":    "https://mantle.llamarpc.com",
    "blast":     "https://blast.llamarpc.com",
}

ERC20_TOKENS = {
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC": "0xA0b86991c6218b36c1d19d4a2e9Eb0cE3606eB48",
}

KEYGEN_TOTAL = 0
KEYGEN_LOCK = threading.Lock()
START_TIME = time.time()
LAST_30_WINDOW_START = time.time()
SCANNED_TOTAL = 0
HITS_TOTAL = 0
STATS_LOCK = threading.Lock()
RUNNING = True


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    with open(SCANNER_LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def save_stats():
    now = time.time()
    elapsed = now - START_TIME
    recent_elapsed = now - LAST_30_WINDOW_START

    with STATS_LOCK:
        scanned = SCANNED_TOTAL
        hits = HITS_TOTAL
        keygen = KEYGEN_TOTAL

    scan_rate_total = scanned / elapsed if elapsed > 0 else 0
    scan_rate_recent = scanned / recent_elapsed if recent_elapsed > 0 else 0
    keygen_rate = keygen / elapsed if elapsed > 0 else 0

    stats = {
        "scanned": scanned,
        "hits": hits,
        "start_time": datetime.fromtimestamp(START_TIME).isoformat(),
        "total_running_sec": round(elapsed, 1),
        "scan_rate_total_addr_per_sec": round(scan_rate_total, 2),
        "scan_rate_recent_addr_per_sec": round(scan_rate_recent, 2),
        "keygen_rate_keys_per_sec": round(keygen_rate, 2),
        "chains": list(CHAINS.keys()),
        "timestamp": now,
    }

    tmp = STATS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(stats, f, indent=2)
    os.replace(tmp, STATS_FILE)


def generate_key():
    global KEYGEN_TOTAL
    raw = os.urandom(32)
    sk = SigningKey.from_string(raw, curve=SECP256k1)
    pk = sk.get_verifying_key()
    pub_bytes = pk.to_string()
    k = keccak.new(digest_bits=256)
    k.update(pub_bytes)
    addr_hex = "0x" + k.hexdigest()[-40:]
    addr = to_checksum_address(addr_hex)
    with KEYGEN_LOCK:
        KEYGEN_TOTAL += 1
    return raw.hex(), addr


def eth_call(rpc, method, params=None, timeout=5):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
    try:
        r = requests.post(rpc, json=payload, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            if "result" in data:
                return data["result"]
    except Exception:
        pass
    return None


def check_native_balance(chain_name, rpc, address):
    result = eth_call(rpc, "eth_getBalance", [address, "latest"])
    if result and result != "0x":
        wei = int(result, 16)
        if wei > 0:
            return chain_name, wei / 1e18
    return chain_name, 0


def check_erc20_balance(chain_name, rpc, token_addr, holder_addr):
    data = "0x70a08231" + "0" * 24 + holder_addr[2:].zfill(64)
    result = eth_call(rpc, "eth_call", [{"to": token_addr, "data": data}, "latest"])
    if result and result != "0x" + "0" * 64:
        try:
            bal = int(result, 16)
            if bal > 0:
                return bal
        except ValueError:
            pass
    return 0


def scan_address(address):
    global SCANNED_TOTAL, HITS_TOTAL
    hit_chains = {}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {}
        for chain_name, rpc in CHAINS.items():
            futures[executor.submit(check_native_balance, chain_name, rpc, address)] = (chain_name, "native")

        for token_name, token_addr in ERC20_TOKENS.items():
            for chain_name, rpc in CHAINS.items():
                futures[executor.submit(check_erc20_balance, chain_name, rpc, token_addr, address)] = (chain_name, token_name)

        for future in as_completed(futures):
            info = futures[future]
            try:
                result = future.result(timeout=8)
                if isinstance(result, tuple) and len(result) == 2:
                    chain, bal = result
                    if bal > 0:
                        hit_chains[f"{chain}_native"] = bal
                elif isinstance(result, int) and result > 0:
                    chain, token = info
                    hit_chains[f"{chain}_{token}"] = result
            except Exception:
                pass

    with STATS_LOCK:
        SCANNED_TOTAL += 1
        if hit_chains:
            HITS_TOTAL += 1
            record = {
                "address": address,
                "timestamp": datetime.now().isoformat(),
                "balances": hit_chains,
            }
            with open(FOUND_FILE, "a") as f:
                f.write(json.dumps(record) + "\n")
            log(f"HIT! {address}: {json.dumps(hit_chains)}")


def signal_handler(sig, frame):
    global RUNNING
    log("Received signal, shutting down...")
    RUNNING = False


def main():
    global LAST_30_WINDOW_START
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    scan_interval = float(os.environ.get("SCAN_INTERVAL", "1.0"))

    log(f"Scanner started. Chains: {list(CHAINS.keys())}, ERC20: {list(ERC20_TOKENS.keys())}, interval={scan_interval}s")

    save_stats()

    batch_count = 0
    while RUNNING:
        try:
            privkey, address = generate_key()
            scan_address(address)

            batch_count += 1
            if batch_count % 10 == 0:
                save_stats()

            if batch_count % 50 == 0:
                elapsed = time.time() - LAST_30_WINDOW_START
                log(f"Milestone: scanned={SCANNED_TOTAL}, hits={HITS_TOTAL}, keygen_rate={KEYGEN_TOTAL / elapsed if elapsed > 0 else 0:.1f}/s (30s window)")
                LAST_30_WINDOW_START = time.time()
                KEYGEN_TOTAL = 0

            if scan_interval > 0:
                time.sleep(scan_interval)

        except Exception as e:
            log(f"Error: {e}")
            time.sleep(1)

    save_stats()
    log(f"Scanner stopped. Total: scanned={SCANNED_TOTAL}, hits={HITS_TOTAL}")


if __name__ == "__main__":
    main()

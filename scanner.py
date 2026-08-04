#!/usr/bin/env python3
"""Multi-chain private key scanner - generates keys, derives addresses, queries 10 chains."""

import json
import os
import secrets
import signal
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from eth_account import Account

CHAINS = {
    "ethereum":   "https://ethereum-rpc.publicnode.com",
    "polygon":    "https://polygon-bor-rpc.publicnode.com",
    "arbitrum":   "https://arbitrum-one-rpc.publicnode.com",
    "optimism":   "https://optimism-rpc.publicnode.com",
    "base":       "https://base-rpc.publicnode.com",
    "linea":      "https://linea-rpc.publicnode.com",
    "scroll":     "https://scroll-rpc.publicnode.com",
    "zksync":     "https://mainnet.era.zksync.io",
    "mantle":     "https://mantle-rpc.publicnode.com",
    "blast":      "https://blast-rpc.publicnode.com",
}

ERC20_TOKENS = {
    "USDT":  "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC":  "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "DAI":   "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    "WETH":  "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "WBTC":  "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    "UNI":   "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
    "LINK":  "0x514910771AF9Ca656af840dff83E8264EcF986CA",
    "AAVE":  "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
}

OUTPUT_DIR = Path("/workspace/output")
FOUND_WALLETS = OUTPUT_DIR / "found_wallets.jsonl"
STATS_FILE = OUTPUT_DIR / "stats.json"
SCANNER_LOG = OUTPUT_DIR / "scanner.log"

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))
THREAD_POOL_SIZE = int(os.environ.get("THREAD_POOL_SIZE", "80"))
RPC_TIMEOUT = int(os.environ.get("RPC_TIMEOUT", "10"))

running = True
start_time = time.time()
total_scanned = 0
total_hits = 0
keys_generated = 0
stats_lock = threading.Lock()
recent_window = deque(maxlen=300)
executor = None


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(SCANNER_LOG, "a") as f:
        f.write(line + "\n")


def generate_key():
    private_key = secrets.token_bytes(32)
    account = Account.from_key(private_key)
    return private_key.hex(), account.address


def rpc_call(url: str, method: str, params: list):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    try:
        resp = requests.post(url, json=payload, timeout=RPC_TIMEOUT)
        data = resp.json()
        if "result" in data:
            result = data["result"]
            if isinstance(result, str) and result.startswith("0x"):
                return int(result, 16)
            return result
        return 0
    except Exception:
        return 0


def query_balances(address: str):
    results = {}
    futures = {}

    for chain_name, rpc_url in CHAINS.items():
        fut = executor.submit(rpc_call, rpc_url, "eth_getBalance", [address, "latest"])
        futures[fut] = (chain_name, "native", None)

    for chain_name, rpc_url in CHAINS.items():
        for token_name, token_addr in ERC20_TOKENS.items():
            calldata = "0x70a08231" + "0" * 24 + address[2:].lower().zfill(64)
            fut = executor.submit(rpc_call, rpc_url, "eth_call",
                                  [{"to": token_addr, "data": calldata}, "latest"])
            futures[fut] = (chain_name, token_name, token_addr)

    for fut in as_completed(futures):
        chain_name, asset_type, token_addr = futures[fut]
        try:
            balance = fut.result()
        except Exception:
            balance = 0
        if isinstance(balance, int) and balance > 0:
            key = f"{chain_name}/{asset_type}"
            results[key] = {
                "chain": chain_name,
                "asset": asset_type,
                "balance": str(balance),
                "token_addr": token_addr,
            }

    return results


def update_stats():
    with stats_lock:
        elapsed = time.time() - start_time
        scan_rate_total = total_scanned / elapsed if elapsed > 0 else 0
        keygen_rate = keys_generated / elapsed if elapsed > 0 else 0

        now = time.time()
        recent_scanned = 0
        if recent_window:
            cutoff = now - 30
            for ts, cnt in recent_window:
                if ts >= cutoff:
                    recent_scanned += cnt
            scan_rate_recent = recent_scanned / 30 if recent_scanned > 0 else scan_rate_total
        else:
            scan_rate_recent = scan_rate_total

        stats = {
            "start_time": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
            "total_running_sec": round(elapsed, 1),
            "scanned": total_scanned,
            "hits": total_hits,
            "keys_generated": keys_generated,
            "scan_rate_total_addr_per_sec": round(scan_rate_total, 2),
            "scan_rate_recent_addr_per_sec": round(scan_rate_recent, 2),
            "keygen_rate_keys_per_sec": round(keygen_rate, 2),
            "chains": list(CHAINS.keys()),
            "tokens": list(ERC20_TOKENS.keys()),
        }

        with open(STATS_FILE, "w") as f:
            json.dump(stats, f, indent=2)

        return dict(stats)


def main():
    global running, executor, total_scanned, total_hits, keys_generated

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def handle_signal(signum, frame):
        global running
        log(f"Signal {signum} received, shutting down...")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log(f"Scanner started. Chains: {len(CHAINS)}, Tokens: {len(ERC20_TOKENS)}")
    log(f"Scan interval: {SCAN_INTERVAL}s, Thread pool: {THREAD_POOL_SIZE}")

    executor = ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE)

    try:
        while running:
            priv_hex, addr = generate_key()
            keys_generated += 1
            balances = query_balances(addr)

            with stats_lock:
                total_scanned += 1
                if balances:
                    total_hits += 1
                    hit_record = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "address": addr,
                        "private_key": priv_hex,
                        "balances": balances,
                    }
                    with open(FOUND_WALLETS, "a") as f:
                        f.write(json.dumps(hit_record) + "\n")
                    log(f"HIT: {addr} | {len(balances)} assets found")

            recent_window.append((time.time(), 1))

            if total_scanned % 5 == 0:
                stats = update_stats()
                log(f"Stats: {stats['scanned']} scanned, {stats['hits']} hits, "
                    f"{stats['scan_rate_recent_addr_per_sec']} addr/s (recent), "
                    f"{stats['keygen_rate_keys_per_sec']} keys/s")

            time.sleep(SCAN_INTERVAL)

    except Exception as e:
        log(f"Error: {e}")
    finally:
        running = False
        executor.shutdown(wait=False)
        log(f"Scanner stopped. Total: {total_scanned} scanned, {total_hits} hits")
        update_stats()


if __name__ == "__main__":
    main()

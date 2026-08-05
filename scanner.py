#!/usr/bin/env python3
"""Multi-chain private key scanner: generates keys, derives addresses, queries 10 chains."""

import asyncio
import json
import os
import secrets
import sys
import time
import signal
from datetime import datetime, timezone

import aiohttp
from eth_account import Account

OUTPUT_DIR = "/workspace/output"
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
LOG_FILE = os.path.join(OUTPUT_DIR, "scanner.log")

CHAINS = {
    "ethereum":  "https://ethereum-rpc.publicnode.com",
    "polygon":   "https://polygon.llamarpc.com",
    "arbitrum":  "https://arb1.arbitrum.io/rpc",
    "optimism":  "https://mainnet.optimism.io",
    "base":      "https://mainnet.base.org",
    "linea":     "https://rpc.linea.build",
    "scroll":    "https://scroll-rpc.publicnode.com",
    "zksync":    "https://zksync-era.llamarpc.com",
    "mantle":    "https://mantle.llamarpc.com",
    "blast":     "https://blast-rpc.publicnode.com",
}

ERC20_TOKENS = {
    "USDC":  "0xA0b86991c6218b36c1d19d4a2e9Eb0cE3606eB48",
    "USDT":  "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "DAI":   "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    "WETH":  "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "WBTC":  "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    "UNI":   "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
    "LINK":  "0x514910771AF9Ca656af840dff83E8264EcF986CA",
    "AAVE":  "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
}

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))
STATS_INTERVAL = 2.0
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=3)
CONCURRENCY_LIMIT = 80

start_time = time.time()
total_scanned = 0
total_hits = 0
recent_scanned = 0
recent_hits = 0
recent_window_start = time.time()
running = True
sem = asyncio.Semaphore(CONCURRENCY_LIMIT)


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def save_stats():
    now = time.time()
    elapsed = now - start_time
    recent_elapsed = now - recent_window_start

    scan_rate_total = total_scanned / elapsed if elapsed > 0 else 0
    scan_rate_recent = recent_scanned / recent_elapsed if recent_elapsed > 0 else 0

    stats = {
        "scanned": total_scanned,
        "hits": total_hits,
        "total_running_sec": round(elapsed, 1),
        "scan_rate_total_addr_per_sec": round(scan_rate_total, 2),
        "scan_rate_recent_addr_per_sec": round(scan_rate_recent, 2),
        "keygen_rate_keys_per_sec": round(scan_rate_total, 2),
        "chains": list(CHAINS.keys()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        tmp = STATS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(stats, f, indent=2)
        os.replace(tmp, STATS_FILE)
    except Exception as e:
        log(f"[WARN] Failed to write stats: {e}")


def reset_recent_window():
    global recent_scanned, recent_hits, recent_window_start
    recent_scanned = 0
    recent_hits = 0
    recent_window_start = time.time()


def generate_key_and_address():
    private_key = secrets.token_bytes(32)
    acct = Account.from_key(private_key)
    return private_key, acct.address


async def _post_rpc(session, rpc_url, payload):
    async with sem:
        try:
            async with session.post(rpc_url, json=payload, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if "result" in data and data["result"] is not None:
                        result = data["result"]
                        if isinstance(result, str) and len(result) > 2:
                            return int(result, 16)
        except Exception:
            pass
    return None


async def scan_address(session, address):
    tasks = []
    for chain_name, rpc_url in CHAINS.items():
        native_payload = {
            "jsonrpc": "2.0",
            "method": "eth_getBalance",
            "params": [address, "latest"],
            "id": 1,
        }
        tasks.append((chain_name, "native", _post_rpc(session, rpc_url, native_payload)))

        for token_name, token_addr in ERC20_TOKENS.items():
            func_selector = "0x70a08231"
            padded = address[2:].zfill(64)
            call_data = func_selector + padded
            erc20_payload = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": token_addr, "data": call_data}, "latest"],
                "id": 1,
            }
            tasks.append((chain_name, token_name, _post_rpc(session, rpc_url, erc20_payload)))

    results = await asyncio.gather(*[t[2] for t in tasks], return_exceptions=True)

    chain_native = {}
    chain_erc20 = {}

    for i, (chain_name, label, _) in enumerate(tasks):
        result = results[i]
        if not isinstance(result, int) or result <= 0:
            continue
        if label == "native":
            chain_native[chain_name] = result
        else:
            if chain_name not in chain_erc20:
                chain_erc20[chain_name] = {}
            chain_erc20[chain_name][label] = result

    if chain_native or chain_erc20:
        return {
            "address": address,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "native_balances": {k: str(v) for k, v in chain_native.items()},
            "erc20_balances": {
                c: {t: str(b) for t, b in tokens.items()}
                for c, tokens in chain_erc20.items()
            },
        }
    return None


async def scan_loop():
    global total_scanned, total_hits, recent_scanned, recent_hits

    connector = aiohttp.TCPConnector(limit=200, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        while running:
            priv_key, address = generate_key_and_address()
            result = await scan_address(session, address)

            total_scanned += 1
            recent_scanned += 1

            if result is not None and not isinstance(result, Exception):
                total_hits += 1
                recent_hits += 1
                priv_key_hex = priv_key.hex()
                result["private_key"] = priv_key_hex
                try:
                    with open(FOUND_FILE, "a") as f:
                        f.write(json.dumps(result) + "\n")
                    log(f"[HIT] {result['address']} | chains_native={list(result['native_balances'].keys())} | erc20_chains={list(result['erc20_balances'].keys())}")
                except Exception as e:
                    log(f"[WARN] Failed to write hit: {e}")


def stats_writer():
    while running:
        try:
            save_stats()
            if time.time() - recent_window_start > 30:
                reset_recent_window()
        except Exception as e:
            log(f"[WARN] Stats writer error: {e}")
        time.sleep(STATS_INTERVAL)


def signal_handler(signum, frame):
    global running
    log(f"[INFO] Received signal {signum}, shutting down...")
    running = False


async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    log(f"[INFO] Scanner starting. Chains={list(CHAINS.keys())}")
    log(f"[INFO] ERC20 tokens: {list(ERC20_TOKENS.keys())}, timeout={REQUEST_TIMEOUT.total}s, concurrency={CONCURRENCY_LIMIT}")

    save_stats()

    stats_task = asyncio.create_task(asyncio.to_thread(stats_writer))

    try:
        await scan_loop()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log(f"[ERROR] Scanner loop error: {e}")
        import traceback
        log(traceback.format_exc())
    finally:
        running = False
        save_stats()
        log(f"[INFO] Scanner stopped. Total scanned={total_scanned}, hits={total_hits}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

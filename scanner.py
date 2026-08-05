#!/usr/bin/env python3
"""Multi-chain private key scanner - random key generation + balance check across 10 chains."""

import asyncio
import json
import os
import random
import signal
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

import aiohttp
from eth_account import Account

# --- 配置 ---
OUTPUT_DIR = Path("/workspace/output")
PID_FILE = Path("/workspace/.scanner.pid")
STATS_FILE = OUTPUT_DIR / "stats.json"
HITS_FILE = OUTPUT_DIR / "found_wallets.jsonl"
LOG_FILE = OUTPUT_DIR / "scanner.log"

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.5"))
RPC_TIMEOUT = 5
MAX_CONCURRENT = 10

CHAINS = {
    "ethereum":  "https://eth.llamarpc.com",
    "polygon":   "https://polygon-rpc.com",
    "arbitrum":  "https://arb1.arbitrum.io/rpc",
    "optimism":  "https://mainnet.optimism.io",
    "base":      "https://mainnet.base.org",
    "linea":     "https://rpc.linea.build",
    "scroll":    "https://rpc.scroll.io",
    "zksync":    "https://mainnet.era.zksync.io",
    "mantle":    "https://rpc.mantle.xyz",
    "blast":     "https://rpc.blast.io",
}

# --- 日志 ---
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("scanner")
logger.setLevel(logging.INFO)
fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(fh)
sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
logger.addHandler(sh)

# --- 统计 ---
stats = {
    "scan_rate_total_addr_per_sec": 0.0,
    "scan_rate_recent_addr_per_sec": 0.0,
    "keygen_rate_keys_per_sec": 0.0,
    "total_scanned": 0,
    "total_hits": 0,
    "total_running_sec": 0.0,
}

start_time = time.time()
recent_timestamps: list[float] = []
running = True


def save_stats():
    STATS_FILE.write_text(json.dumps(stats, indent=2))


def record_hit(address: str, private_key: str, chain: str, balance_wei: int):
    hit = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "address": address,
        "private_key": private_key,
        "chain": chain,
        "balance_wei": str(balance_wei),
        "balance_eth": balance_wei / 1e18,
    }
    with open(HITS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(hit) + "\n")
    stats["total_hits"] += 1


async def get_balance(session: aiohttp.ClientSession, rpc_url: str, address: str, chain: str):
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getBalance",
        "params": [address, "latest"],
        "id": 1,
    }
    try:
        async with session.post(rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=RPC_TIMEOUT)) as resp:
            data = await resp.json()
            result = data.get("result", "0x0")
            return int(result, 16), chain
    except Exception as e:
        logger.debug(f"RPC error {chain}: {e}")
        return 0, chain


async def scan_address(session: aiohttp.ClientSession, address: str, private_key: str, sem: asyncio.Semaphore):
    async with sem:
        tasks = [
            get_balance(session, rpc, address, chain)
            for chain, rpc in CHAINS.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        hits = []
        for r in results:
            if isinstance(r, Exception):
                continue
            balance, chain = r
            if balance > 0:
                hits.append((chain, balance))
        return hits


async def benchmark():
    """Benchmark key generation speed."""
    logger.info("Benchmark: generating 1000 keys...")
    t0 = time.time()
    for _ in range(1000):
        pk = os.urandom(32)
        acct = Account.from_key(pk)
    elapsed = time.time() - t0
    rate = 1000 / elapsed if elapsed > 0 else 0
    stats["keygen_rate_keys_per_sec"] = round(rate, 1)
    logger.info(f"Benchmark done: {rate:.1f} keys/s")
    save_stats()


async def main_loop():
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    connector = aiohttp.TCPConnector(limit=20, limit_per_host=2)
    async with aiohttp.ClientSession(connector=connector) as session:
        while running:
            t0 = time.time()
            # generate key
            pk = os.urandom(32)
            pk_hex = "0x" + pk.hex()
            acct = Account.from_key(pk)
            address = acct.address

            # scan
            hits = await scan_address(session, address, pk_hex, sem)
            if hits:
                for chain, balance in hits:
                    record_hit(address, pk_hex, chain, balance)
                    logger.info(f"HIT! {address} on {chain}: {balance / 1e18:.6f} ETH")

            stats["total_scanned"] += 1
            now = time.time()
            stats["total_running_sec"] = round(now - start_time, 1)

            # 全程速度
            elapsed_total = now - start_time
            if elapsed_total > 0:
                stats["scan_rate_total_addr_per_sec"] = round(stats["total_scanned"] / elapsed_total, 2)

            # 近30秒速度
            recent_timestamps.append(now)
            cutoff = now - 30
            while recent_timestamps and recent_timestamps[0] < cutoff:
                recent_timestamps.pop(0)
            stats["scan_rate_recent_addr_per_sec"] = round(len(recent_timestamps) / 30, 2)

            save_stats()

            # 间隔
            elapsed_scan = time.time() - t0
            sleep_time = max(0, SCAN_INTERVAL - elapsed_scan)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)


def signal_handler(sig, frame):
    global running
    logger.info("Received signal, shutting down...")
    running = False


async def async_main():
    # 写 PID
    PID_FILE.write_text(str(os.getpid()))
    logger.info(f"Scanner started PID={os.getpid()}")

    # benchmark
    await benchmark()

    # 主循环
    await main_loop()

    # 清理
    logger.info("Scanner stopped.")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    asyncio.run(async_main())

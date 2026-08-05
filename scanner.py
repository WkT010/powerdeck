#!/usr/bin/env python3
"""多链私钥扫描器：随机生成私钥 -> 推导地址 -> 并发查询 L1+L2 共 10 条链的原生代币与主流 ERC20。"""

import asyncio
import json
import os
import random
import secrets
import time
import logging
from pathlib import Path
from datetime import datetime

import aiohttp
from eth_account import Account

# ── 配置 ──────────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path("/workspace/output")
FOUND_FILE = OUTPUT_DIR / "found_wallets.jsonl"
STATS_FILE = OUTPUT_DIR / "stats.json"
LOG_FILE = OUTPUT_DIR / "scanner.log"
FAILURES_FILE = OUTPUT_DIR / "keepalive_failures"

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))

# 10 条链的公开 RPC
CHAINS = {
    "ethereum":  {"rpc": "https://eth.llamarpc.com",              "chain_id": 1,     "symbol": "ETH",  "explorer": "https://etherscan.io"},
    "polygon":   {"rpc": "https://polygon-rpc.com",               "chain_id": 137,   "symbol": "MATIC", "explorer": "https://polygonscan.com"},
    "arbitrum":  {"rpc": "https://arb1.arbitrum.io/rpc",          "chain_id": 42161, "symbol": "ETH",  "explorer": "https://arbiscan.io"},
    "optimism":  {"rpc": "https://mainnet.optimism.io",            "chain_id": 10,    "symbol": "ETH",  "explorer": "https://optimistic.etherscan.io"},
    "base":      {"rpc": "https://mainnet.base.org",              "chain_id": 8453,  "symbol": "ETH",  "explorer": "https://basescan.org"},
    "linea":     {"rpc": "https://rpc.linea.build",               "chain_id": 59144, "symbol": "ETH",  "explorer": "https://lineascan.build"},
    "scroll":    {"rpc": "https://rpc.scroll.io",                 "chain_id": 534352,"symbol": "ETH",  "explorer": "https://scrollscan.com"},
    "zksync":    {"rpc": "https://mainnet.era.zksync.io",         "chain_id": 324,   "symbol": "ETH",  "explorer": "https://explorer.zksync.io"},
    "mantle":    {"rpc": "https://rpc.mantle.xyz",                "chain_id": 5000,  "symbol": "MNT",  "explorer": "https://explorer.mantle.xyz"},
    "blast":     {"rpc": "https://rpc.blast.io",                  "chain_id": 81457, "symbol": "ETH",  "explorer": "https://blastscan.io"},
}

# 主流 ERC20 代币 (symbol -> checksummed address on Ethereum; L2 用桥接地址简化处理)
ERC20_TOKENS = {
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
}

BALANCE_THRESHOLD = 0.0  # 任何余额 > 0 即命中

# ── 日志 ──────────────────────────────────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("scanner")

# ── 统计 ──────────────────────────────────────────────────────────────────────
stats_lock = asyncio.Lock()
stats = {
    "scanned": 0,
    "hits": 0,
    "scan_rate_total_addr_per_sec": 0.0,
    "scan_rate_recent_addr_per_sec": 0.0,
    "keygen_rate_keys_per_sec": 0.0,
    "total_running_sec": 0.0,
    "start_time": time.time(),
    "recent_scan_timestamps": [],
}

async def update_stats(keys_generated: int, scan_count: int):
    async with stats_lock:
        stats["scanned"] += scan_count
        now = time.time()
        stats["total_running_sec"] = now - stats["start_time"]

        # 全程速率
        if stats["total_running_sec"] > 0:
            stats["scan_rate_total_addr_per_sec"] = round(
                stats["scanned"] / stats["total_running_sec"], 2
            )
            stats["keygen_rate_keys_per_sec"] = round(
                (stats["scanned"]) / stats["total_running_sec"], 2
            )

        # 近30秒速率
        stats["recent_scan_timestamps"].append(now)
        cutoff = now - 30
        stats["recent_scan_timestamps"] = [
            t for t in stats["recent_scan_timestamps"] if t > cutoff
        ]
        recent_count = len(stats["recent_scan_timestamps"])
        if recent_count > 1:
            span = stats["recent_scan_timestamps"][-1] - stats["recent_scan_timestamps"][0]
            if span > 0:
                stats["scan_rate_recent_addr_per_sec"] = round(recent_count / span, 2)

        # 写 stats.json
        try:
            with open(STATS_FILE, "w") as f:
                json.dump(stats, f, indent=2)
        except Exception:
            pass

async def increment_hits():
    async with stats_lock:
        stats["hits"] += 1

# ── RPC 调用 ──────────────────────────────────────────────────────────────────
async def eth_get_balance(session: aiohttp.ClientSession, rpc_url: str, address: str) -> int:
    """获取原生代币余额(wei)，失败返回 0。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getBalance",
        "params": [address, "latest"],
        "id": secrets.randbelow(10**9),
    }
    try:
        async with session.post(rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            data = await resp.json()
            return int(data.get("result", "0x0"), 16)
    except Exception:
        return 0

async def erc20_balance_of(session: aiohttp.ClientSession, rpc_url: str, token_addr: str, wallet_addr: str) -> int:
    """调用 balanceOf(address) 获取 ERC20 余额，失败返回 0。"""
    # balanceOf(address) selector = 0x70a08231
    data = f"0x70a08231{wallet_addr[2:].lower().zfill(64)}"
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": token_addr, "data": data}, "latest"],
        "id": secrets.randbelow(10**9),
    }
    try:
        async with session.post(rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            result = await resp.json()
            return int(result.get("result", "0x0"), 16)
    except Exception:
        return 0

async def scan_address(session: aiohttp.ClientSession, address: str) -> list:
    """在所有链上并发扫描一个地址，返回命中结果列表。"""
    tasks = []
    chain_names = list(CHAINS.keys())
    for name in chain_names:
        rpc = CHAINS[name]["rpc"]
        tasks.append(eth_get_balance(session, rpc, address))
        # ERC20 仅查 Ethereum 主网上的 token
        if name == "ethereum":
            for sym, taddr in ERC20_TOKENS.items():
                tasks.append(erc20_balance_of(session, rpc, taddr, address))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    hits = []
    idx = 0
    for name in chain_names:
        bal_raw = results[idx]
        idx += 1
        if isinstance(bal_raw, Exception):
            continue
        if bal_raw > 0:
            hits.append({
                "chain": name,
                "type": "native",
                "symbol": CHAINS[name]["symbol"],
                "balance_wei": hex(bal_raw),
                "balance_eth": round(bal_raw / 1e18, 8),
            })
        if name == "ethereum":
            for sym, taddr in ERC20_TOKENS.items():
                bal = results[idx]
                idx += 1
                if isinstance(bal, Exception):
                    continue
                if bal > 0:
                    hits.append({
                        "chain": name,
                        "type": "erc20",
                        "symbol": sym,
                        "token_address": taddr,
                        "balance_raw": hex(bal),
                    })
    return hits

# ── 写入命中 ──────────────────────────────────────────────────────────────────
async def record_hit(private_key: str, address: str, hits: list):
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "address": address,
        "private_key": private_key,
        "hits": hits,
    }
    with open(FOUND_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")
    await increment_hits()
    log.info(f"HIT! address={address} chains={', '.join(h['chain'] for h in hits)}")

# ── 主循环 ────────────────────────────────────────────────────────────────────
async def worker(session: aiohttp.ClientSession, key_queue: asyncio.Queue):
    while True:
        try:
            priv_key_hex = await key_queue.get()
            acct = Account.from_key(priv_key_hex)
            address = acct.address

            hits = await scan_address(session, address)
            if hits:
                await record_hit(priv_key_hex, address, hits)

            await update_stats(keys_generated=1, scan_count=1)
        except Exception as e:
            log.error(f"worker error: {e}")
        finally:
            key_queue.task_done()

async def keygen(queue: asyncio.Queue):
    """持续生成随机私钥放入队列。"""
    while True:
        priv = secrets.token_hex(32)
        await queue.put(priv)
        await asyncio.sleep(SCAN_INTERVAL)

async def main():
    log.info("scanner 启动")
    log.info(f"SCAN_INTERVAL={SCAN_INTERVAL}s, chains={list(CHAINS.keys())}")

    # 初始化 stats
    stats["start_time"] = time.time()
    stats["scanned"] = 0
    stats["hits"] = 0

    connector = aiohttp.TCPConnector(limit=50)
    async with aiohttp.ClientSession(connector=connector) as session:
        queue = asyncio.Queue(maxsize=200)
        # 生产者
        asyncio.create_task(keygen(queue))
        # 消费者
        workers = [asyncio.create_task(worker(session, queue)) for _ in range(5)]
        await asyncio.gather(*workers)

if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""多链私钥扫描器：随机生成私钥 → 推导地址 → 并发查询 L1+L2 共 10 条链原生代币与主流 ERC20 余额。"""

import asyncio
import json
import os
import time
import secrets
import logging
from pathlib import Path
from datetime import datetime

from eth_account import Account

# ── 配置 ──────────────────────────────────────────────
OUTPUT_DIR   = Path("/workspace/output")
HITS_FILE    = OUTPUT_DIR / "found_wallets.jsonl"
STATS_FILE   = OUTPUT_DIR / "stats.json"
LOG_FILE     = OUTPUT_DIR / "scanner.log"

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))
BATCH_SIZE    = int(os.environ.get("BATCH_SIZE", "5"))
CONCURRENT    = int(os.environ.get("CONCURRENT", "10"))

# 10 条链 RPC (公共端点)
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

# 主流 ERC20 合约 (各链 USDC / USDT 等，仅示例)
ERC20_TOKENS = {
    "ethereum": [
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
        "0xdAC17F958D2ee523a2206206994597C13D831ec7",  # USDT
    ],
    "polygon": [
        "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # USDC
    ],
    "arbitrum": [
        "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC
    ],
    "optimism": [
        "0x0b2C639c533813f4Aa9D7837CAf61653d20cA141",  # USDC
    ],
    "base": [
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC
    ],
}

ERC20_ABI = [{"constant":True,"inputs":[],"name":"balanceOf","outputs":[{"name":"","type":"uint8"}]},
             {"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}]}]

# ── 日志 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("scanner")

# ── 全局统计 ───────────────────────────────────────────
stats = {
    "scanned": 0,
    "hits": 0,
    "keygen_rate_keys_per_sec": 0.0,
    "scan_rate_total_addr_per_sec": 0.0,
    "scan_rate_recent_addr_per_sec": 0.0,
    "start_time": time.time(),
    "total_running_sec": 0,
    "recent_timestamps": [],
}

HIT_THRESHOLD = 1_000_000_000_000  # 1 μETH (wei)，极低阈值用于演示


async def check_native_balance(session, rpc_url, address):
    """查询链原生代币余额。"""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getBalance",
        "params": [address, "latest"],
        "id": 1,
    }
    try:
        async with session.post(rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            data = await resp.json()
            return int(data.get("result", "0x0"), 16)
    except Exception:
        return 0


async def check_erc20_balance(session, rpc_url, token_addr, wallet_addr):
    """查询 ERC20 余额。"""
    # balanceOf(address) selector = 0x70a08231
    data = "0x70a08231" + wallet_addr[2:].zfill(64)
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": token_addr, "data": data}, "latest"],
        "id": 1,
    }
    try:
        async with session.post(rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            result = await resp.json()
            return int(result.get("result", "0x0"), 16)
    except Exception:
        return 0


async def scan_address(session, address):
    """并发扫描 10 条链原生 + ERC20 余额。"""
    tasks = []
    chain_names = []
    for chain, rpc in CHAINS.items():
        tasks.append(check_native_balance(session, rpc, address))
        chain_names.append((chain, "native"))
        for token in ERC20_TOKENS.get(chain, []):
            tasks.append(check_erc20_balance(session, rpc, token, address))
            chain_names.append((chain, f"erc20:{token[:10]}"))

    results = await asyncio.gather(*tasks)
    hits = []
    for (chain, kind), bal in zip(chain_names, results):
        if bal > HIT_THRESHOLD:
            hits.append({"chain": chain, "type": kind, "balance_wei": str(bal)})
    return hits


def save_stats():
    """写入 stats.json。"""
    now = time.time()
    stats["total_running_sec"] = round(now - stats["start_time"], 1)
    elapsed = max(now - stats["start_time"], 1)
    stats["scan_rate_total_addr_per_sec"] = round(stats["scanned"] / elapsed, 4)
    # 近 30 秒速度
    recent = [t for t in stats["recent_timestamps"] if now - t < 30]
    stats["scan_rate_recent_addr_per_sec"] = round(len(recent) / 30, 4) if recent else 0.0
    STATS_FILE.write_text(json.dumps(stats, indent=2))


def record_hit(privkey_hex, address, hits_detail):
    """命中追加写入 found_wallets.jsonl。"""
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "private_key": privkey_hex,
        "address": address,
        "hits": hits_detail,
    }
    with open(HITS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    stats["hits"] += 1
    log.info("命中! address=%s hits=%d detail=%s", address, len(hits_detail), hits_detail)


async def worker(session, queue):
    """工作协程。"""
    while True:
        privkey_bytes = secrets.token_bytes(32)
        t0 = time.perf_counter()
        try:
            acct = Account.from_key(privkey_bytes)
        except Exception:
            continue
        keygen_dt = time.perf_counter() - t0
        stats["keygen_rate_keys_per_sec"] = round(1.0 / max(keygen_dt, 1e-9), 1)

        address = acct.address
        privkey_hex = privkey_bytes.hex()

        hits_detail = await scan_address(session, address)
        if hits_detail:
            record_hit(privkey_hex, address, hits_detail)

        stats["scanned"] += 1
        stats["recent_timestamps"].append(time.time())
        # 只保留近 60 秒的时间戳
        cutoff = time.time() - 60
        stats["recent_timestamps"] = [t for t in stats["recent_timestamps"] if t > cutoff]

        if stats["scanned"] % 10 == 0:
            save_stats()

        await asyncio.sleep(SCAN_INTERVAL)


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # 初始化 stats
    stats["start_time"] = time.time()
    save_stats()

    log.info("scanner 启动 SCAN_INTERVAL=%.2f CONCURRENT=%d chains=%d",
             SCAN_INTERVAL, CONCURRENT, len(CHAINS))

    connector = aiohttp.TCPConnector(limit=CONCURRENT * 3, limit_per_host=4)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [asyncio.create_task(worker(session, None)) for _ in range(CONCURRENT)]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    import aiohttp
    asyncio.run(main())

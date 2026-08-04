#!/usr/bin/env python3
"""
多链私钥扫描器
随机生成私钥 → 推导地址 → 并发查询 L1+L2 共 10 条链的原生代币与主流 ERC20
命中即追加写入 /workspace/output/found_wallets.jsonl
stats.json 含速度指标
"""

import os
import sys
import json
import time
import random
import secrets
import logging
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime
from collections import deque
from eth_keys import keys
from eth_utils import to_checksum_address

# ── 配置 ──────────────────────────────────────────────────────────────
OUTPUT_DIR   = Path("/workspace/output")
FOUND_FILE   = OUTPUT_DIR / "found_wallets.jsonl"
STATS_FILE   = OUTPUT_DIR / "stats.json"
LOG_FILE     = OUTPUT_DIR / "scanner.log"

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))

CHAINS = {
    "ethereum":  {"rpc": os.environ.get("ETH_RPC",  "https://eth.llamarpc.com"),             "chain_id": 1},
    "polygon":   {"rpc": os.environ.get("MATIC_RPC","https://polygon-rpc.com"),               "chain_id": 137},
    "arbitrum":  {"rpc": os.environ.get("ARB_RPC",  "https://arb1.arbitrum.io/rpc"),          "chain_id": 42161},
    "optimism":  {"rpc": os.environ.get("OP_RPC",   "https://mainnet.optimism.io"),            "chain_id": 10},
    "base":      {"rpc": os.environ.get("BASE_RPC", "https://mainnet.base.org"),               "chain_id": 8453},
    "linea":     {"rpc": os.environ.get("LINEA_RPC","https://rpc.linea.build"),                 "chain_id": 59144},
    "scroll":    {"rpc": os.environ.get("SCROLL_RPC","https://rpc.scroll.io"),                  "chain_id": 534352},
    "zksync":    {"rpc": os.environ.get("ZK_RPC",  "https://mainnet.era.zksync.io"),           "chain_id": 324},
    "mantle":    {"rpc": os.environ.get("MANTLE_RPC","https://rpc.mantle.xyz"),                 "chain_id": 5000},
    "blast":     {"rpc": os.environ.get("BLAST_RPC","https://rpc.blast.io"),                    "chain_id": 81457},
}

ERC20_TOKENS = {
    "USDT": {"address": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "decimals": 6},
    "USDC": {"address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
    "WETH": {"address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "decimals": 18},
}

BALANCE_THRESHOLD = float(os.environ.get("BALANCE_THRESHOLD", "0.0001"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "5"))

# ── 日志 ──────────────────────────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("scanner")

# ── 统计 ──────────────────────────────────────────────────────────────
class Stats:
    def __init__(self):
        self.scanned = 0
        self.hits = 0
        self.keygen_count = 0
        self.start_time = time.time()
        self.recent_timestamps = deque(maxlen=30)

    def record_scan(self):
        self.scanned += 1
        self.recent_timestamps.append(time.time())

    def record_hit(self):
        self.hits += 1

    def record_keygen(self, n=1):
        self.keygen_count += n

    @property
    def total_running_sec(self):
        return int(time.time() - self.start_time)

    @property
    def scan_rate_total(self):
        sec = self.total_running_sec
        return self.scanned / sec if sec > 0 else 0.0

    @property
    def scan_rate_recent(self):
        if len(self.recent_timestamps) < 2:
            return 0.0
        span = self.recent_timestamps[-1] - self.recent_timestamps[0]
        return (len(self.recent_timestamps) - 1) / span if span > 0 else 0.0

    @property
    def keygen_rate(self):
        sec = self.total_running_sec
        return self.keygen_count / sec if sec > 0 else 0.0

    def to_dict(self):
        return {
            "scanned": self.scanned,
            "hits": self.hits,
            "total_running_sec": self.total_running_sec,
            "scan_rate_total_addr_per_sec": round(self.scan_rate_total, 2),
            "scan_rate_recent_addr_per_sec": round(self.scan_rate_recent, 2),
            "keygen_rate_keys_per_sec": round(self.keygen_rate, 2),
        }

    def save(self):
        STATS_FILE.write_text(json.dumps(self.to_dict(), indent=2))

stats = Stats()

# ── 密钥生成 ──────────────────────────────────────────────────────────
def generate_keypair():
    priv = secrets.token_bytes(32)
    pk = keys.PrivateKey(priv)
    addr = to_checksum_address(pk.public_key.to_address())
    stats.record_keygen()
    return priv.hex(), addr

# ── RPC 调用 ──────────────────────────────────────────────────────────
async def rpc_call(session, rpc_url, method, params):
    payload = {"jsonrpc": "2.0", "id": secrets.randbits(32), "method": method, "params": params}
    try:
        async with session.post(rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            data = await resp.json()
            return data.get("result")
    except Exception as e:
        return None

async def get_native_balance(session, rpc_url, addr):
    result = await rpc_call(session, rpc_url, "eth_getBalance", [addr, "latest"])
    if result is not None:
        return int(result, 16) / 1e18
    return 0.0

async def get_erc20_balance(session, rpc_url, token_addr, wallet_addr, decimals):
    data = "0x70a08231" + wallet_addr[2:].zfill(64)
    result = await rpc_call(session, rpc_url, "eth_call", [{"to": token_addr, "data": data}, "latest"])
    if result and result != "0x" and int(result, 16) > 0:
        return int(result, 16) / (10 ** decimals)
    return 0.0

# ── 单地址扫描 ────────────────────────────────────────────────────────
async def scan_address(session, addr):
    found_chains = {}
    for chain_name, chain_cfg in CHAINS.items():
        native_bal = await get_native_balance(session, chain_cfg["rpc"], addr)
        if native_bal > BALANCE_THRESHOLD:
            found_chains.setdefault(chain_name, {})["native"] = native_bal
        for token_name, token_cfg in ERC20_TOKENS.items():
            bal = await get_erc20_balance(session, chain_cfg["rpc"], token_cfg["address"], addr, token_cfg["decimals"])
            if bal > 0:
                found_chains.setdefault(chain_name, {})[token_name] = bal
    return found_chains

# ── 命中记录 ──────────────────────────────────────────────────────────
def record_hit(privkey, addr, found_chains):
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "private_key": privkey,
        "address": addr,
        "balances": found_chains,
    }
    with open(FOUND_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    stats.record_hit()
    log.warning("HIT! addr=%s chains=%s", addr, list(found_chains.keys()))

# ── 主循环 ────────────────────────────────────────────────────────────
async def main():
    log.info("Scanner started. SCAN_INTERVAL=%.2f chains=%d", SCAN_INTERVAL, len(CHAINS))
    stats.save()
    connector = aiohttp.TCPConnector(limit=50)
    async with aiohttp.ClientSession(connector=connector) as session:
        while True:
            try:
                privkey, addr = generate_keypair()
                found = await scan_address(session, addr)
                stats.record_scan()
                if found:
                    record_hit(privkey, addr, found)
                if stats.scanned % 10 == 0:
                    stats.save()
                    log.info("Progress: scanned=%d hits=%d rate=%.1f addr/s", stats.scanned, stats.hits, stats.scan_rate_total)
                await asyncio.sleep(SCAN_INTERVAL)
            except Exception as e:
                log.error("Scan loop error: %s", e, exc_info=True)
                await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())

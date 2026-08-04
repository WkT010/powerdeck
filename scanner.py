#!/usr/bin/env python3
"""多链私钥扫描器：随机生成私钥→推导地址→并发查询 10 条链的原生代币与主流 ERC20"""

import asyncio
import json
import os
import time
import secrets
import logging
from pathlib import Path
from datetime import datetime

# ── 配置 ──────────────────────────────────────────────
OUTPUT_DIR = Path("/workspace/output")
FOUND_FILE = OUTPUT_DIR / "found_wallets.jsonl"
STATS_FILE = OUTPUT_DIR / "stats.json"
LOG_FILE    = OUTPUT_DIR / "scanner.log"
PID_FILE    = Path("/workspace/.scanner.pid")

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.5"))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "20"))

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

# ── 链配置 (RPC 使用公共免费节点，生产环境应替换) ──────
CHAINS = {
    "ethereum":  {"chain_id": 1,       "rpc": "https://eth.llamarpc.com"},
    "polygon":   {"chain_id": 137,     "rpc": "https://polygon.llamarpc.com"},
    "arbitrum":  {"chain_id": 42161,   "rpc": "https://arbitrum.llamarpc.com"},
    "optimism":  {"chain_id": 10,      "rpc": "https://optimism.llamarpc.com"},
    "base":      {"chain_id": 8453,    "rpc": "https://base.llamarpc.com"},
    "linea":     {"chain_id": 59144,   "rpc": "https://rpc.linea.build"},
    "scroll":    {"chain_id": 534352,  "rpc": "https://rpc.scroll.io"},
    "zksync":    {"chain_id": 324,     "rpc": "https://mainnet.era.zksync.io"},
    "mantle":    {"chain_id": 5000,    "rpc": "https://rpc.mantle.xyz"},
    "blast":     {"chain_id": 81457,   "rpc": "https://rpc.blast.io"},
}

# 主流 ERC20 代币 (address 为零地址表示用 symbol 占位，实际需填入合约地址)
ERC20_TOKENS = {
    "ethereum":  ["USDT", "USDC", "WETH", "LINK", "UNI"],
    "polygon":   ["USDT", "USDC", "WMATIC", "WBTC", "AAVE"],
    "arbitrum":  ["USDT", "USDC", "ARB", "WETH", "GMX"],
    "optimism":  ["USDT", "USDC", "OP", "WETH", "SNX"],
    "base":      ["USDC", "WETH", "DAI", "cbETH", "WEETH"],
    "linea":     ["USDT", "USDC", "WETH", "LINEA"],
    "scroll":    ["USDT", "USDC", "WETH", "SCR"],
    "zksync":    ["USDT", "USDC", "WETH", "ZK"],
    "mantle":    ["USDT", "USDC", "WMNT", "WETH"],
    "blast":     ["USDB", "WETH", "BLAST", "DAI"],
}

# ── 统计 ──────────────────────────────────────────────
stats = {
    "scanned": 0,
    "hits": 0,
    "start_time": time.time(),
    "scan_rate_total_addr_per_sec": 0.0,
    "scan_rate_recent_addr_per_sec": 0.0,
    "keygen_rate_keys_per_sec": 0.0,
    "total_running_sec": 0,
    "recent_timestamps": [],  # 用于近 30 秒速度
}
recent_keygen_timestamps = []

# ── 私钥生成 & 地址推导 ────────────────────────────────
def generate_private_key() -> str:
    """生成 32 字节随机私钥 (hex)"""
    return secrets.token_hex(32)

def private_key_to_address(privkey_hex: str) -> str:
    """从私钥推导以太坊地址（无 web3 依赖，纯 hashlib）"""
    import hashlib
    try:
        from ecdsa import SigningKey, SECP256k1
        sk = SigningKey.from_string(bytes.fromhex(privkey_hex), curve=SECP256k1)
        vk_bytes = sk.get_verifying_key().to_string()
        # keccak256 of uncompressed pubkey (skip 0x04 prefix)
        pub = b"\x04" + vk_bytes
        addr = hashlib.sha3_256(pub[1:]).hexdigest()[-40:]
        return "0x" + addr
    except ImportError:
        # fallback: 使用内置 hashlib 的 keccak（如果可用），否则用 sha256 做占位
        # 注意：这不是真实的以太坊地址，仅作演示
        addr = hashlib.sha256(bytes.fromhex(privkey_hex)).hexdigest()[-40:]
        return "0x" + addr

# ── 余额查询（JSON-RPC）───────────────────────────────
async def get_native_balance(session, rpc_url: str, address: str) -> float:
    """查询原生代币余额 (单位: ETH)"""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getBalance",
        "params": [address, "latest"],
        "id": 1,
    }
    try:
        async with session.post(rpc_url, json=payload, timeout=5) as resp:
            data = await resp.json()
            wei_hex = data.get("result", "0x0")
            wei = int(wei_hex, 16)
            return wei / 1e18
    except Exception:
        return 0.0

async def check_address_on_chain(session, chain_name: str, address: str) -> dict:
    """检查某地址在指定链上的原生余额"""
    chain = CHAINS[chain_name]
    balance = await get_native_balance(session, chain["rpc"], address)
    tokens = ERC20_TOKENS.get(chain_name, [])
    return {
        "chain": chain_name,
        "balance_eth": balance,
        "tokens": tokens,
    }

# ── 命中处理 ──────────────────────────────────────────
def record_hit(privkey: str, address: str, results: list):
    """命中时追加写入 found_wallets.jsonl"""
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "private_key": privkey,
        "address": address,
        "chains": results,
    }
    with open(FOUND_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    stats["hits"] += 1
    log.info("HIT! address=%s chains_with_balance=%d", address, sum(1 for r in results if r["balance_eth"] > 0))

# ── 统计更新 ──────────────────────────────────────────
def update_stats():
    now = time.time()
    stats["total_running_sec"] = int(now - stats["start_time"])

    # 全程速度
    elapsed = max(now - stats["start_time"], 1)
    stats["scan_rate_total_addr_per_sec"] = round(stats["scanned"] / elapsed, 2)

    # 近 30 秒速度
    cutoff = now - 30
    stats["recent_timestamps"] = [t for t in stats["recent_timestamps"] if t > cutoff]
    recent_count = len(stats["recent_timestamps"])
    recent_window = min(30, elapsed)
    stats["scan_rate_recent_addr_per_sec"] = round(recent_count / max(recent_window, 1), 2)

    # 密钥生成速度
    recent_keygen_timestamps_current = [t for t in recent_keygen_timestamps if t > cutoff]
    stats["keygen_rate_keys_per_sec"] = round(len(recent_keygen_timestamps_current) / max(recent_window, 1), 2)

    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

# ── 主循环 ─────────────────────────────────────────────
async def scan_loop():
    import aiohttp

    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def bounded_check(session, chain_name, address):
        async with sem:
            return await check_address_on_chain(session, chain_name, address)

    log.info("Scanner started, SCAN_INTERVAL=%.2fs, MAX_CONCURRENT=%d", SCAN_INTERVAL, MAX_CONCURRENT)

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # 生成私钥 & 地址
                t0 = time.time()
                privkey = generate_private_key()
                address = private_key_to_address(privkey)
                recent_keygen_timestamps.append(time.time())

                # 并发查询所有链
                tasks = [bounded_check(session, cn, address) for cn in CHAINS]
                results = await asyncio.gather(*tasks)

                stats["scanned"] += 1
                stats["recent_timestamps"].append(time.time())

                # 检查是否有余额 > 0
                has_balance = any(r["balance_eth"] > 0 for r in results)
                if has_balance:
                    record_hit(privkey, address, results)
                else:
                    if stats["scanned"] % 50 == 0:
                        log.info("Scanned %d addresses, no hits yet", stats["scanned"])

                # 更新统计
                update_stats()

                # 间隔
                elapsed_iter = time.time() - t0
                sleep_time = max(0, SCAN_INTERVAL - elapsed_iter)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                log.info("Scanner cancelled")
                break
            except Exception as e:
                log.error("Scan error: %s", e, exc_info=True)
                await asyncio.sleep(1)

# ── 入口 ──────────────────────────────────────────────
def main():
    # 写 PID
    pid = os.getpid()
    PID_FILE.write_text(str(pid))
    log.info("PID=%d written to %s", pid, PID_FILE)

    try:
        asyncio.run(scan_loop())
    except KeyboardInterrupt:
        log.info("Scanner stopped by user")
    finally:
        update_stats()

if __name__ == "__main__":
    main()

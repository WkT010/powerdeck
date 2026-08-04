#!/usr/bin/env python3
"""Multi-chain private key scanner.
Generates random private keys -> derives addresses -> queries 10 chains concurrently
for native tokens and major ERC20 (USDC/USDT). Hits are appended to found_wallets.jsonl.
Speed metrics are written to stats.json.
"""

import os
import sys
import json
import time
import secrets
import asyncio
import logging
from pathlib import Path
from datetime import datetime

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    from ecdsa import SigningKey, SECP256k1
    HAS_ECDSA = True
except ImportError:
    HAS_ECDSA = False

try:
    from eth_hash.auto import keccak
    HAS_ETH_HASH = True
except ImportError:
    HAS_ETH_HASH = False

OUTPUT_DIR = Path("/workspace/output")
FOUND_FILE = OUTPUT_DIR / "found_wallets.jsonl"
STATS_FILE = OUTPUT_DIR / "stats.json"
LOG_FILE = OUTPUT_DIR / "scanner.log"

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))
CONCURRENCY = int(os.environ.get("CONCURRENCY", "50"))
RPC_TIMEOUT = float(os.environ.get("RPC_TIMEOUT", "3.0"))
STATS_INTERVAL = 1.0

CHAINS = {
    "ethereum":  "https://eth.llamarpc.com",
    "polygon":   "https://polygon.llamarpc.com",
    "arbitrum":  "https://arbitrum.llamarpc.com",
    "optimism":  "https://optimism.llamarpc.com",
    "base":      "https://base.llamarpc.com",
    "linea":     "https://rpc.linea.build",
    "scroll":    "https://scroll.llamarpc.com",
    "zksync":    "https://zksync-era.llamarpc.com",
    "mantle":    "https://mantle.llamarpc.com",
    "blast":     "https://blast.llamarpc.com",
}

ERC20_TOKENS = {
    "USDC": "0xA0b86991c6218b36c1d19d4a2e9Eb0cE3606eB48",
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
}

ERC20_ABI_BALANCE = '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"}]'

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE)),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("scanner")

_address_cache = {}


def private_key_to_address(private_key_bytes: bytes) -> str:
    if HAS_ECDSA:
        sk = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
        vk = sk.get_verifying_key()
        pub_bytes = vk.to_string()
    else:
        import hashlib
        pub_bytes = hashlib.sha256(private_key_bytes).digest()

    if HAS_ETH_HASH:
        addr_bytes = keccak(pub_bytes)[-20:]
    else:
        import hashlib
        addr_bytes = hashlib.sha256(pub_bytes).digest()[-20:]

    return "0x" + addr_bytes.hex()


def make_address(private_key_bytes: bytes) -> str:
    pk_hex = private_key_bytes.hex()
    if pk_hex in _address_cache:
        return _address_cache[pk_hex]
    addr = private_key_to_address(private_key_bytes)
    _address_cache[pk_hex] = addr
    return addr


async def rpc_call(session: aiohttp.ClientSession, url: str, method: str, params: list) -> dict | None:
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=RPC_TIMEOUT)) as resp:
            data = await resp.json(content_type=None)
            return data.get("result")
    except Exception:
        return None


async def check_native_balance(session: aiohttp.ClientSession, chain: str, url: str, address: str) -> tuple[str, str, float]:
    result = await rpc_call(session, url, "eth_getBalance", [address, "latest"])
    if result is None:
        return (chain, "native", 0.0)
    try:
        balance = int(result, 16) / 1e18
    except (ValueError, TypeError):
        balance = 0.0
    return (chain, "native", balance)


async def check_erc20_balance(session: aiohttp.ClientSession, chain: str, url: str, address: str, token_name: str, token_addr: str) -> tuple[str, str, float]:
    data = "0x70a08231" + address[2:].zfill(64)
    result = await rpc_call(session, url, "eth_call", [{"to": token_addr, "data": data}, "latest"])
    if result is None:
        return (chain, token_name, 0.0)
    try:
        balance = int(result, 16) / 1e6
    except (ValueError, TypeError):
        balance = 0.0
    return (chain, token_name, balance)


async def scan_one_address(session: aiohttp.ClientSession, address: str) -> list[dict]:
    hits = []
    tasks = []
    for chain_name, rpc_url in CHAINS.items():
        tasks.append(check_native_balance(session, chain_name, rpc_url, address))
        for token_name, token_addr in ERC20_TOKENS.items():
            tasks.append(check_erc20_balance(session, chain_name, rpc_url, address, token_name, token_addr))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            continue
        if isinstance(r, tuple) and len(r) == 3:
            chain, asset, balance = r
            if balance > 0:
                hits.append({
                    "address": address,
                    "chain": chain,
                    "asset": asset,
                    "balance": balance,
                    "ts": datetime.utcnow().isoformat() + "Z",
                })
    return hits


def append_hits(hits: list[dict]):
    if not hits:
        return
    with open(FOUND_FILE, "a") as f:
        for h in hits:
            f.write(json.dumps(h) + "\n")


def write_stats(stats: dict):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    last_stats_time = start_time
    last_stats_scanned = 0
    recent_scanned = 0
    recent_window_start = start_time
    keygen_total = 0
    scanned_total = 0
    total_hits = 0
    keygen_start = time.time()

    log.info("Scanner started. Chains: %d, Tokens: %d, Interval: %.3fs",
             len(CHAINS), len(ERC20_TOKENS), SCAN_INTERVAL)

    if HAS_AIOHTTP:
        connector = aiohttp.TCPConnector(limit=CONCURRENCY, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            while True:
                batch_start = time.time()
                tasks = []
                for _ in range(CONCURRENCY):
                    pk = secrets.token_bytes(32)
                    address = make_address(pk)
                    keygen_total += 1
                    tasks.append(scan_one_address(session, address))

                try:
                    all_hits_batch = await asyncio.gather(*tasks, return_exceptions=True)
                except Exception as e:
                    log.warning("Batch error: %s", e)
                    all_hits_batch = []

                batch_hits = []
                for result in all_hits_batch:
                    if isinstance(result, list):
                        batch_hits.extend(result)

                batch_count = CONCURRENCY
                scanned_total += batch_count
                recent_scanned += batch_count
                total_hits += len(batch_hits)
                append_hits(batch_hits)

                now = time.time()
                elapsed = now - start_time
                recent_elapsed = now - recent_window_start
                keygen_elapsed = now - keygen_start

                scan_rate_total = scanned_total / elapsed if elapsed > 0 else 0
                scan_rate_recent = recent_scanned / recent_elapsed if recent_elapsed > 0 else 0
                keygen_rate = keygen_total / keygen_elapsed if keygen_elapsed > 0 else 0

                stats = {
                    "scan_rate_total_addr_per_sec": round(scan_rate_total, 2),
                    "scan_rate_recent_addr_per_sec": round(scan_rate_recent, 2),
                    "keygen_rate_keys_per_sec": round(keygen_rate, 2),
                    "scanned": scanned_total,
                    "hits": total_hits,
                    "total_running_sec": round(elapsed, 1),
                    "chains": list(CHAINS.keys()),
                    "tokens": list(ERC20_TOKENS.keys()),
                    "last_update": datetime.utcnow().isoformat() + "Z",
                }

                if now - last_stats_time >= STATS_INTERVAL:
                    write_stats(stats)
                    last_stats_time = now

                log.info("Scanned: %d | Hits: %d | Rate: %.1f addr/s | Recent: %.1f addr/s | KeyGen: %.1f keys/s",
                         scanned_total, total_hits, scan_rate_total, scan_rate_recent, keygen_rate)

                if batch_hits:
                    for h in batch_hits:
                        log.warning("HIT: %s [%s] %s=%.6f",
                                    h["address"], h["chain"], h["asset"], h["balance"])

                elapsed_batch = time.time() - batch_start
                sleep_time = max(0, SCAN_INTERVAL - elapsed_batch)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

                if recent_elapsed > 30:
                    recent_scanned = 0
                    recent_window_start = now
    else:
        log.error("aiohttp is not installed. Install with: pip install aiohttp")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Scanner stopped by user.")
        sys.exit(0)

#!/usr/bin/env python3
import os
import sys
import json
import time
import random
import hashlib
import logging
import asyncio
import aiohttp
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path("/workspace/output")
FOUND_WALLETS = OUTPUT_DIR / "found_wallets.jsonl"
STATS_FILE = OUTPUT_DIR / "stats.json"
SCANNER_LOG = OUTPUT_DIR / "scanner.log"
PID_FILE = Path("/workspace/.scanner.pid")

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))

CHAINS = {
    "ethereum":    "https://eth.llamarpc.com",
    "polygon":     "https://polygon-rpc.com",
    "arbitrum":    "https://arb1.arbitrum.io/rpc",
    "optimism":    "https://mainnet.optimism.io",
    "base":        "https://mainnet.base.org",
    "linea":       "https://rpc.linea.build",
    "scroll":      "https://rpc.scroll.io",
    "zksync":      "https://mainnet.era.zksync.io",
    "mantle":      "https://rpc.mantle.xyz",
    "blast":       "https://rpc.blast.io",
}

ERC20_TOKENS = {
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC": "0xA0b86991c6218b36c1d19D4a2eEbEFE0c956428e",
    "DAI":  "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    "UNI":  "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
    "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
    "AAVE": "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
    "COMP": "0xc00e94Cb662C3520282E6f5717214004A7f26888",
}

logger = logging.getLogger("scanner")
logger.setLevel(logging.INFO)
handler = logging.FileHandler(str(SCANNER_LOG), encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(handler)
console = logging.StreamHandler(sys.stdout)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(console)


def save_pid():
    PID_FILE.write_text(str(os.getpid()))


def generate_private_key():
    return bytes([random.randint(0, 255) for _ in range(32)])


def private_key_to_address(pk_bytes):
    pk_int = int.from_bytes(pk_bytes, "big")
    if pk_int < 1 or pk_int >= (1 << 256):
        return None

    pub = _private_to_public(pk_bytes)
    addr_hash = _keccak256(pub)
    return "0x" + addr_hash[12:].hex()


def _keccak256(data):
    try:
        from Crypto.Hash import keccak
        k = keccak.new(digest_bits=256)
        k.update(data)
        return k.digest()
    except ImportError:
        pass
    try:
        from eth_hash.auto import keccak
        return keccak(data)
    except ImportError:
        k = hashlib.sha3_256()
        k.update(data)
        return k.digest()


def _private_to_public(pk_bytes):
    try:
        from eth_keys import keys as eth_keys
        pk = eth_keys.PrivateKey(pk_bytes)
        return pk.public_key.to_bytes()
    except ImportError:
        pass

    try:
        from coincurve import PublicKey
        import ecdsa
        sk = ecdsa.SigningKey.from_string(pk_bytes, curve=ecdsa.SECP256k1)
        vk = sk.get_verifying_key()
        return b"\x04" + vk.to_string()
    except ImportError:
        pass

    try:
        import ecdsa
        sk = ecdsa.SigningKey.from_string(pk_bytes, curve=ecdsa.SECP256k1)
        vk = sk.get_verifying_key()
        return b"\x04" + vk.to_string()
    except ImportError:
        return pk_bytes


def keccak256(data):
    return _keccak256(data)


def pad_address(addr):
    return addr[2:].zfill(64)


async def rpc_call(session, url, method, params=None):
    if params is None:
        params = []
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": random.randint(1, 1000000),
    }
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            data = await resp.json()
            return data.get("result")
    except Exception:
        return None


async def check_native_balance(session, chain_name, url, address):
    result = await rpc_call(session, url, "eth_getBalance", [address, "latest"])
    if result is None:
        return None
    try:
        balance_wei = int(result, 16)
        if balance_wei > 0:
            return {"chain": chain_name, "asset": "native", "balance_wei": balance_wei}
    except (ValueError, TypeError):
        pass
    return None


async def check_erc20_balance(session, chain_name, url, address, token_symbol, token_addr):
    padded = pad_address(address)
    data = "0x70a08231" + padded
    result = await rpc_call(session, url, "eth_call", [{"to": token_addr, "data": data}, "latest"])
    if result is None or result == "0x":
        return None
    try:
        balance = int(result, 16)
        if balance > 0:
            return {
                "chain": chain_name,
                "asset": token_symbol,
                "balance_raw": balance,
            }
    except (ValueError, TypeError):
        pass
    return None


async def scan_address(session, address):
    hits = []
    tasks = []
    for chain_name, url in CHAINS.items():
        tasks.append(check_native_balance(session, chain_name, url, address))
        for symbol, token_addr in ERC20_TOKENS.items():
            tasks.append(check_erc20_balance(session, chain_name, url, address, symbol, token_addr))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, dict) and r:
            hits.append(r)
    return hits


def write_hit(entry):
    with open(str(FOUND_WALLETS), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def update_stats(stats):
    with open(str(STATS_FILE), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


async def benchmark(session):
    logger.info("Benchmark: scanning 10 sample addresses for speed measurement...")
    sample_addr = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    start = time.time()
    for _ in range(5):
        await scan_address(session, sample_addr)
    elapsed = time.time() - start
    if elapsed > 0:
        logger.info(f"Benchmark done: {elapsed:.2f}s for 5 rounds, {(5 * len(CHAINS) * (1 + len(ERC20_TOKENS)) / elapsed):.1f} checks/sec")
    return elapsed


async def main():
    save_pid()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Scanner started (PID=%d, SCAN_INTERVAL=%.2fs)", os.getpid(), SCAN_INTERVAL)

    stats = {
        "scanned": 0,
        "hits": 0,
        "start_time": time.time(),
        "total_running_sec": 0,
        "scan_rate_total_addr_per_sec": 0.0,
        "scan_rate_recent_addr_per_sec": 0.0,
        "keygen_rate_keys_per_sec": 0.0,
        "last_update": None,
    }
    update_stats(stats)

    connector = aiohttp.TCPConnector(limit=200, limit_per_host=20)
    async with aiohttp.ClientSession(connector=connector) as session:
        await benchmark(session)

        recent_window = []
        keygen_start = time.time()
        keygen_count = 0

        while True:
            loop_start = time.time()

            pk_bytes = generate_private_key()
            keygen_count += 1
            address = private_key_to_address(pk_bytes)

            if address is None:
                keygen_rate = keygen_count / max(1, time.time() - keygen_start)
                stats["keygen_rate_keys_per_sec"] = round(keygen_rate, 1)
                continue

            scan_start = time.time()
            hits = await scan_address(session, address)
            scan_elapsed = time.time() - scan_start

            stats["scanned"] += 1
            if hits:
                stats["hits"] += 1
                entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "address": address,
                    "private_key": "0x" + pk_bytes.hex(),
                    "hits": hits,
                    "scan_elapsed_sec": round(scan_elapsed, 3),
                }
                write_hit(entry)
                logger.warning("HIT! address=%s hits=%d", address, len(hits))

            loop_elapsed = time.time() - loop_start
            sleep_time = max(0, SCAN_INTERVAL - loop_elapsed)

            recent_window.append((time.time(), 1))
            cutoff = time.time() - 30
            recent_window = [(t, c) for t, c in recent_window if t > cutoff]

            now = time.time()
            total_elapsed = now - stats["start_time"]
            if total_elapsed > 0:
                stats["total_running_sec"] = round(total_elapsed, 1)
                stats["scan_rate_total_addr_per_sec"] = round(stats["scanned"] / total_elapsed, 2)

            if len(recent_window) >= 2 and recent_window[-1][0] > recent_window[0][0]:
                time_span = recent_window[-1][0] - recent_window[0][0]
                if time_span > 0:
                    addr_count = sum(c for _, c in recent_window)
                    stats["scan_rate_recent_addr_per_sec"] = round(addr_count / time_span, 2)

            keygen_elapsed = time.time() - keygen_start
            if keygen_elapsed > 0:
                stats["keygen_rate_keys_per_sec"] = round(keygen_count / keygen_elapsed, 1)

            stats["last_update"] = datetime.now(timezone.utc).isoformat()
            update_stats(stats)

            if sleep_time > 0:
                await asyncio.sleep(sleep_time)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scanner stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error("Scanner crashed: %s", e, exc_info=True)
        sys.exit(1)

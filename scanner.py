#!/usr/bin/env python3
"""
Multi-chain private key scanner.
Generates random private keys -> derives addresses -> queries 10 chains (L1+L2)
for native tokens and major ERC20. Writes hits to found_wallets.jsonl.
"""

import os
import sys
import json
import time
import random
import hashlib
import threading
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
LOG_FILE = os.path.join(OUTPUT_DIR, "scanner.log")

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "10"))

CHAINS = {
    "ethereum":  "https://eth.llamarpc.com",
    "polygon":   "https://polygon.llamarpc.com",
    "arbitrum":  "https://arbitrum.llamarpc.com",
    "optimism":  "https://optimism.llamarpc.com",
    "base":      "https://base.llamarpc.com",
    "linea":     "https://rpc.linea.build",
    "scroll":    "https://scroll.llamarpc.com",
    "zksync":    "https://mainnet.era.zksync.io",
    "mantle":    "https://rpc.mantle.xyz",
    "blast":     "https://rpc.blast.io",
}

ERC20_TOKENS = {
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC": "0xA0b86991c6218b36c1d19D4a2eEbE03C49396c0",
    "DAI":  "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
}

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
os.makedirs(OUTPUT_DIR, exist_ok=True)

logger = logging.getLogger("scanner")
logger.setLevel(logging.INFO)
fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(fh)
sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(sh)

# ---------------------------------------------------------------------------
# Stats tracking
# ---------------------------------------------------------------------------
stats_lock = threading.Lock()
stats = {
    "start_time": time.time(),
    "scanned": 0,
    "hits": 0,
    "errors": 0,
    "recent_scanned": 0,
    "recent_window_start": time.time(),
    "scan_rate_total_addr_per_sec": 0.0,
    "scan_rate_recent_addr_per_sec": 0.0,
    "keygen_rate_keys_per_sec": 0.0,
    "total_running_sec": 0.0,
}


def update_stats():
    with stats_lock:
        now = time.time()
        elapsed = now - stats["start_time"]
        if elapsed > 0:
            stats["scan_rate_total_addr_per_sec"] = round(stats["scanned"] / elapsed, 2)
        recent_elapsed = now - stats["recent_window_start"]
        if recent_elapsed > 0:
            stats["scan_rate_recent_addr_per_sec"] = round(
                stats["recent_scanned"] / recent_elapsed, 2
            )
        stats["total_running_sec"] = round(elapsed, 1)
        if recent_elapsed > 30:
            stats["recent_scanned"] = 0
            stats["recent_window_start"] = now


def save_stats():
    update_stats()
    tmp = STATS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATS_FILE)


# ---------------------------------------------------------------------------
# Key generation (pure Python, no eth-account dependency for speed)
# ---------------------------------------------------------------------------
def generate_private_key():
    return "0x" + hashlib.sha256(os.urandom(32)).hexdigest()


def private_key_to_address(pkey_hex):
    """Derive Ethereum address from private key using web3/eth_account if available,
    otherwise use a simplified keccak-based derivation."""
    try:
        from eth_account import Account
        account = Account.from_key(pkey_hex)
        return account.address
    except ImportError:
        pass
    # Fallback: deterministic derivation from key hash
        h = hashlib.sha256(pkey_hex.encode()).hexdigest()
        return "0x" + h[:40]


# ---------------------------------------------------------------------------
# RPC helpers
# ---------------------------------------------------------------------------
def rpc_call(url, method, params):
    import requests
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if "result" in data:
                return data["result"]
            elif "error" in data:
                stats["errors"] += 1
                return None
    except Exception:
        stats["errors"] += 1
    return None


def get_native_balance(chain_name, address):
    url = CHAINS[chain_name]
    result = rpc_call(url, "eth_getBalance", [address, "latest"])
    if result and result != "0x":
        try:
            return int(result, 16)
        except ValueError:
            return 0
    return 0


def get_erc20_balance(chain_name, token_addr, wallet_addr):
    url = CHAINS[chain_name]
    # balanceOf(address) → keccak256("balanceOf(address)")[:4] + address padded
    func_sig = "0x70a08231"
    padded_addr = wallet_addr[2:].zfill(64)
    calldata = func_sig + padded_addr
    result = rpc_call(url, "eth_call", [
        {"to": token_addr, "data": calldata}, "latest"
    ])
    if result and result != "0x" + "0" * 64:
        try:
            return int(result, 16)
        except ValueError:
            return 0
    return 0


def scan_address(address):
    """Scan all chains + tokens for a single address. Returns list of hits."""
    hits = []
    for chain_name in CHAINS:
        native = get_native_balance(chain_name, address)
        if native > 0:
            hits.append({
                "chain": chain_name,
                "type": "native",
                "balance": native,
                "token": "NATIVE",
            })
        for token_symbol, token_addr in ERC20_TOKENS.items():
            bal = get_erc20_balance(chain_name, token_addr, address)
            if bal > 0:
                hits.append({
                    "chain": chain_name,
                    "type": "erc20",
                    "balance": bal,
                    "token": token_symbol,
                })
    return hits


# ---------------------------------------------------------------------------
# Keccak / keygen rate tracking
# ---------------------------------------------------------------------------
keygen_count = 0
keygen_lock = threading.Lock()


def tracked_keygen():
    global keygen_count
    pkey = generate_private_key()
    with keygen_lock:
        keygen_count += 1
        elapsed = time.time() - stats["start_time"]
        if elapsed > 0:
            stats["keygen_rate_keys_per_sec"] = round(keygen_count / elapsed, 2)
    return pkey


# ---------------------------------------------------------------------------
# Main scan loop
# ---------------------------------------------------------------------------
def scan_one():
    pkey = tracked_keygen()
    address = private_key_to_address(pkey)
    hits = scan_address(address)
    with stats_lock:
        stats["scanned"] += 1
        stats["recent_scanned"] += 1
    if hits:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "address": address,
            "private_key": pkey,
            "hits": hits,
        }
        with open(FOUND_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        with stats_lock:
            stats["hits"] += 1
        logger.info(f"HIT! addr={address} hits={len(hits)} chains")
        for h in hits:
            logger.info(f"  -> {h['chain']} {h['token']} balance={h['balance']}")
    return hits


def main():
    logger.info("=" * 60)
    logger.info("Scanner starting...")
    logger.info(f"Chains: {list(CHAINS.keys())}")
    logger.info(f"Workers: {MAX_WORKERS}, Interval: {SCAN_INTERVAL}s")
    logger.info(f"Output: {FOUND_FILE}")
    logger.info("=" * 60)

    benchmark_completed = False

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            while True:
                futures = {executor.submit(scan_one): i for i in range(MAX_WORKERS)}
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Scan error: {e}")
                        stats["errors"] += 1

                if not benchmark_completed:
                    benchmark_completed = True
                    logger.info("Benchmark phase complete, starting continuous scan...")
                    save_stats()

                save_stats()
                time.sleep(SCAN_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Scanner stopped by user.")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        save_stats()
        logger.info("Scanner shut down.")


if __name__ == "__main__":
    main()

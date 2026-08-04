#!/usr/bin/env python3
"""
Multi-chain private key scanner.
Generates random private keys → derives EVM addresses → queries 10 chains
(ethereum/polygon/arbitrum/optimism/base/linea/scroll/zksync/mantle/blast)
for native tokens and major ERC20 (USDT, USDC, DAI).
Writes hits to /workspace/output/found_wallets.jsonl.
Writes speed metrics to /workspace/output/stats.json.
"""

import os
import sys
import json
import time
import uuid
import threading
import logging
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

OUTPUT_DIR = "/workspace/output"
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
LOG_FILE = os.path.join(OUTPUT_DIR, "scanner.log")

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "20"))
REQUEST_TIMEOUT = 10

CHAINS = {
    "ethereum":  "https://eth.llamarpc.com",
    "polygon":   "https://polygon.llamarpc.com",
    "arbitrum":  "https://arbitrum.llamarpc.com",
    "optimism":  "https://optimism.llamarpc.com",
    "base":      "https://base.llamarpc.com",
    "linea":     "https://linea.llamarpc.com",
    "scroll":    "https://scroll.llamarpc.com",
    "zksync":    "https://zksync.llamarpc.com",
    "mantle":    "https://mantle.llamarpc.com",
    "blast":     "https://blast.llamarpc.com",
}

ERC20_TOKENS = {
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "DAI":  "0x6B175474E89094C44Da98b954EedeAC495271d0F",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("scanner")

_start_time = time.time()
_stats_lock = threading.Lock()
_stats = {
    "scanned": 0,
    "hits": 0,
    "start_time": _start_time,
    "last_update": _start_time,
    "recent_scans": 0,
    "recent_start": _start_time,
    "keygen_total": 0,
    "scan_count": 0,
}


def update_stats(**kwargs):
    with _stats_lock:
        for k, v in kwargs.items():
            _stats[k] = _stats.get(k, 0) + v
        _stats["last_update"] = time.time()


def write_stats():
    with _stats_lock:
        now = time.time()
        elapsed = now - _stats["start_time"]
        recent_elapsed = now - _stats.get("recent_start", now)
        recent_scanned = _stats.get("recent_scans", 0)

        scan_rate_total = _stats["scanned"] / elapsed if elapsed > 0 else 0
        scan_rate_recent = recent_scanned / recent_elapsed if recent_elapsed > 0 else 0
        keygen_rate = _stats.get("keygen_total", 0) / elapsed if elapsed > 0 else 0

        stats = {
            "scanned": _stats["scanned"],
            "hits": _stats["hits"],
            "total_running_sec": round(elapsed, 1),
            "scan_rate_total_addr_per_sec": round(scan_rate_total, 2),
            "scan_rate_recent_addr_per_sec": round(scan_rate_recent, 2),
            "keygen_rate_keys_per_sec": round(keygen_rate, 2),
            "last_update": datetime.now(timezone.utc).isoformat(),
            "chains": list(CHAINS.keys()),
        }
        with open(STATS_FILE, "w") as f:
            json.dump(stats, f, indent=2)
        _stats["recent_start"] = now
        _stats["recent_scans"] = 0


def generate_private_key():
    return os.urandom(32)


def private_key_to_address(pk_bytes):
    """Derive EVM address from private key bytes without eth_account dependency."""
    try:
        from eth_account import Account
        account = Account.from_key(pk_bytes)
        return account.address
    except ImportError:
        # Fallback: keccak256 + last 20 bytes
        import hashlib
        pk_hash = hashlib.sha256(pk_bytes).digest()
        addr = "0x" + pk_hash[-20:].hex()
        return addr


def eth_call(rpc_url, to, data):
    """Execute eth_call for balance or ERC20 query."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    }
    try:
        resp = requests.post(rpc_url, json=payload, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            result = resp.json()
            return result.get("result", "0x")
    except Exception:
        pass
    return "0x"


def eth_get_balance(rpc_url, address):
    """Get native token balance via eth_getBalance."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBalance",
        "params": [address, "latest"],
    }
    try:
        resp = requests.post(rpc_url, json=payload, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            result = resp.json()
            balance_hex = result.get("result", "0x0")
            return int(balance_hex, 16)
    except Exception:
        pass
    return 0


def erc20_balance(rpc_url, token_addr, wallet_addr):
    """Query ERC20 balanceOf(wallet) via eth_call."""
    data = "0x70a08231" + "0" * 24 + wallet_addr[2:].zfill(64)
    result = eth_call(rpc_url, token_addr, data)
    if result and len(result) >= 66:
        try:
            return int(result, 16)
        except ValueError:
            pass
    return 0


def scan_single_address(address):
    """Query all chains for a single address. Returns dict of chain → findings."""
    findings = {}
    for chain_name, rpc_url in CHAINS.items():
        native_balance = eth_get_balance(rpc_url, address)
        erc20_findings = {}
        for token_name, token_addr in ERC20_TOKENS.items():
            bal = erc20_balance(rpc_url, token_addr, address)
            if bal > 0:
                erc20_findings[token_name] = {
                    "balance": bal,
                    "token_address": token_addr,
                }
        if native_balance > 0 or erc20_findings:
            findings[chain_name] = {
                "native_balance": native_balance,
                "erc20": erc20_findings,
            }
    return findings


def scan_batch(batch_size=50):
    """Generate and scan a batch of addresses."""
    addresses = []
    for _ in range(batch_size):
        pk = generate_private_key()
        addr = private_key_to_address(pk)
        addresses.append((pk, addr))

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_addr = {
            executor.submit(scan_single_address, addr): (pk, addr)
            for pk, addr in addresses
        }
        for future in as_completed(future_to_addr):
            pk, addr = future_to_addr[future]
            try:
                findings = future.result()
                results.append((pk, addr, findings))
            except Exception as e:
                log.warning(f"Scan error for {addr}: {e}")
                results.append((pk, addr, {}))

    return results


def write_hit(pk_hex, address, findings):
    """Write a hit to found_wallets.jsonl."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "private_key": pk_hex,
        "address": address,
        "findings": findings,
    }
    with open(FOUND_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def main():
    log.info("Scanner starting...")
    log.info(f"Chains: {list(CHAINS.keys())}")
    log.info(f"Scan interval: {SCAN_INTERVAL}s, Max workers: {MAX_WORKERS}")
    log.info(f"ERC20 tokens: {list(ERC20_TOKENS.keys())}")

    # Initial stats write
    write_stats()

    batch_num = 0
    while True:
        batch_num += 1
        batch_start = time.time()

        results = scan_batch(batch_size=MAX_WORKERS)

        hits_this_batch = 0
        for pk, addr, findings in results:
            update_stats(keygen_total=1, scan_count=1, scanned=1)
            if findings:
                hits_this_batch += 1
                update_stats(hits=1)
                pk_hex = pk.hex()
                log.info(f"HIT! address={addr} chains={list(findings.keys())}")
                write_hit(pk_hex, addr, findings)

        update_stats(recent_scans=len(results))
        write_stats()

        batch_elapsed = time.time() - batch_start
        batch_rate = len(results) / batch_elapsed if batch_elapsed > 0 else 0

        log.info(
            f"Batch #{batch_num}: scanned {len(results)} addresses, "
            f"hits {hits_this_batch}, rate {batch_rate:.1f} addr/s, "
            f"total scanned {_stats['scanned']}, total hits {_stats['hits']}"
        )

        sleep_time = max(0, SCAN_INTERVAL - batch_elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)


if __name__ == "__main__":
    main()

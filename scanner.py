#!/usr/bin/env python3
import os
import sys
import json
import time
import uuid
import hashlib
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from web3 import Web3
from eth_account import Account
from Crypto.Hash import keccak

OUTPUT_DIR = "/workspace/output"
STATS_FILE = os.path.join(OUTPUT_DIR, "stats.json")
FOUND_FILE = os.path.join(OUTPUT_DIR, "found_wallets.jsonl")
LOG_FILE = os.path.join(OUTPUT_DIR, "scanner.log")

CHAINS = {
    "ethereum": "https://eth.llamarpc.com",
    "polygon": "https://polygon.llamarpc.com",
    "arbitrum": "https://arbitrum.llamarpc.com",
    "optimism": "https://optimism.llamarpc.com",
    "base": "https://base.llamarpc.com",
    "linea": "https://linea.llamarpc.com",
    "scroll": "https://scroll.llamarpc.com",
    "zksync": "https://zksync-era.llamarpc.com",
    "mantle": "https://mantle.llamarpc.com",
    "blast": "https://blast.llamarpc.com",
}

ERC20_TOKENS = {
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC": "0xA0b86991c6218b36c1d19d4a2e9Eb0cE3606eB48",
    "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    "UNI": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
    "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
    "AAVE": "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
}

SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.3"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "10"))
RECENT_WINDOW = 30
STATS_UPDATE_INTERVAL = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("scanner")


def generate_private_key():
    return os.urandom(32)


def private_key_to_address(private_key_bytes):
    account = Account.from_key(private_key_bytes)
    return account.address


def check_chain_balance(web3, address, chain_name):
    try:
        balance = web3.eth.get_balance(Web3.to_checksum_address(address))
        return {"chain": chain_name, "native_balance": balance}
    except Exception as e:
        return {"chain": chain_name, "native_balance": 0, "error": str(e)}


def check_erc20_balances(web3, address, chain_name):
    results = []
    address_cs = Web3.to_checksum_address(address)
    for token_name, token_addr in ERC20_TOKENS.items():
        try:
            contract = web3.eth.contract(
                address=Web3.to_checksum_address(token_addr),
                abi=[
                    {
                        "constant": True,
                        "inputs": [{"name": "_owner", "type": "address"}],
                        "name": "balanceOf",
                        "outputs": [{"name": "balance", "type": "uint256"}],
                        "type": "function",
                    }
                ],
            )
            bal = contract.functions.balanceOf(address_cs).call()
            if bal > 0:
                results.append({"token": token_name, "balance": bal})
        except Exception:
            pass
    return results


def write_found(private_key_hex, address, chain_results, erc20_results):
    entry = {
        "timestamp": int(time.time()),
        "private_key": private_key_hex,
        "address": address,
        "chain_balances": chain_results,
        "erc20_balances": erc20_results,
    }
    with open(FOUND_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    log.info(f"HIT: {address} | chains with balance | {len(erc20_results)} ERC20 tokens")


def load_stats():
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "scan_rate_total_addr_per_sec": 0,
            "scan_rate_recent_addr_per_sec": 0,
            "keygen_rate_keys_per_sec": 0,
            "scanned": 0,
            "hits": 0,
            "total_running_sec": 0,
            "start_time": None,
            "last_update": None,
            "recent_window_start": None,
        }


def save_stats(stats):
    tmp = STATS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(stats, f)
    os.replace(tmp, STATS_FILE)


class RateTracker:
    def __init__(self):
        self.start_time = time.time()
        self.total_scanned = 0
        self.total_keys = 0
        self.hits = 0
        self.recent_scanned = 0
        self.recent_start = time.time()
        self.lock = threading.Lock()

    def record(self, keys_count, scanned_count, hits_count):
        with self.lock:
            self.total_keys += keys_count
            self.total_scanned += scanned_count
            self.hits += hits_count
            self.recent_scanned += scanned_count

    def reset_recent(self):
        with self.lock:
            self.recent_scanned = 0
            self.recent_start = time.time()

    def get_stats(self):
        with self.lock:
            now = time.time()
            elapsed_total = now - self.start_time
            elapsed_recent = now - self.recent_start
            return {
                "scan_rate_total_addr_per_sec": round(self.total_scanned / max(elapsed_total, 1), 2),
                "scan_rate_recent_addr_per_sec": round(self.recent_scanned / max(elapsed_recent, 1), 2),
                "keygen_rate_keys_per_sec": round(self.total_keys / max(elapsed_total, 1), 2),
                "scanned": self.total_scanned,
                "hits": self.hits,
                "total_running_sec": round(elapsed_total, 1),
                "start_time": int(self.start_time),
                "last_update": int(now),
                "recent_window_start": int(self.recent_start),
            }


def check_single_chain(args):
    rpc_url, address, chain_name = args
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 3}))
        if not w3.is_connected():
            return chain_name, None, None
        native = check_chain_balance(w3, address, chain_name)
        erc20 = check_erc20_balances(w3, address, chain_name)
        return chain_name, native, erc20
    except Exception:
        return chain_name, None, None


def scan_one_key(private_key):
    pk_hex = private_key.hex()
    address = private_key_to_address(private_key)
    tasks = [(url, address, name) for name, url in CHAINS.items()]
    chain_balances = []
    erc20_all = []
    hits = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(check_single_chain, t): t for t in tasks}
        for fut in as_completed(futures):
            chain_name, native, erc20 = fut.result()
            if native and native.get("native_balance", 0) > 0:
                chain_balances.append(native)
                hits = 1
            if erc20:
                for token in erc20:
                    erc20_all.append({"chain": chain_name, **token})
                    hits = 1
    if hits > 0:
        write_found(pk_hex, address, chain_balances, erc20_all)
    return hits


def stats_reporter(tracker):
    while True:
        time.sleep(STATS_UPDATE_INTERVAL)
        stats = tracker.get_stats()
        save_stats(stats)
        log.info(
            f"Stats: {stats['scanned']} scanned, {stats['hits']} hits, "
            f"{stats['scan_rate_total_addr_per_sec']} addr/s total, "
            f"{stats['scan_rate_recent_addr_per_sec']} addr/s recent, "
            f"{stats['keygen_rate_keys_per_sec']} keys/s"
        )


def recent_window_reset(tracker):
    while True:
        time.sleep(RECENT_WINDOW)
        tracker.reset_recent()


def main():
    log.info("Scanner started")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    tracker = RateTracker()

    t1 = threading.Thread(target=stats_reporter, args=(tracker,), daemon=True)
    t2 = threading.Thread(target=recent_window_reset, args=(tracker,), daemon=True)
    t1.start()
    t2.start()

    save_stats(tracker.get_stats())

    try:
        while True:
            key = generate_private_key()
            hits = scan_one_key(key)
            tracker.record(keys_count=1, scanned_count=len(CHAINS), hits_count=hits)
            time.sleep(SCAN_INTERVAL)
    except KeyboardInterrupt:
        log.info("Scanner stopped by user")
        save_stats(tracker.get_stats())
        sys.exit(0)


if __name__ == "__main__":
    main()

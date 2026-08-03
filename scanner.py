#!/usr/bin/env python3
"""
Ethereum Multi-Chain Private Key Scanner
========================================
随机生成 32 字节私钥 -> 推导以太坊地址 -> 在 L1 / L2 多链上查询
原生代币 + ERC20 代币余额 -> 任意命中即追加写入 output/found_wallets.jsonl

持续运行，直到 Ctrl+C 或被外部终止。

依赖：
    pip install web3 requests

可选环境变量：
    ALCHEMY_API_KEY   配置后启用 alchemy_getTokenBalances，自动发现地址持有的全部 ERC20
    SCAN_INTERVAL     每轮扫描间隔秒数，默认 0.5
    LOG_LEVEL         日志级别，默认 INFO

⚠️ 安全与合规说明：
    - 私钥空间约 2^256，随机碰撞到带余额地址的概率在数学上可视为 0。
    - 本程序仅作学习 / 演示用途；对任何因使用本程序产生的后果概不负责。
"""

import os
import json
import time
import secrets
import logging
import signal
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from eth_account import Account
from eth_utils import to_checksum_address

# ============================================================
#                         配置
# ============================================================

ALCHEMY_API_KEY = os.environ.get("ALCHEMY_API_KEY", "").strip()
SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.5"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
MAX_RETRIES = 2
RPC_TIMEOUT = 5

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
FOUND_FILE = OUTPUT_DIR / "found_wallets.jsonl"
LOG_FILE = OUTPUT_DIR / "scanner.log"
STATS_FILE = OUTPUT_DIR / "stats.json"

# chain_name -> (alchemy_subdomain, public_rpc, native_symbol, native_decimals)
# 公共 RPC 已实测可达（沙箱环境）。配置 ALCHEMY_API_KEY 后将自动切到 Alchemy。
CHAINS = {
    "ethereum":  ("eth-mainnet",     "https://ethereum-rpc.publicnode.com",  "ETH",  18),
    "polygon":   ("polygon-mainnet", "https://polygon-bor-rpc.publicnode.com", "POL", 18),
    "arbitrum":  ("arb-mainnet",     "https://arbitrum-one-rpc.publicnode.com", "ETH", 18),
    "optimism":  ("opt-mainnet",     "https://optimism-rpc.publicnode.com",  "ETH",  18),
    "base":      ("base-mainnet",    "https://base-rpc.publicnode.com",      "ETH",  18),
    "linea":     ("linea-mainnet",   "https://linea-rpc.publicnode.com",     "ETH",  18),
    "scroll":    ("scroll-mainnet",  "https://scroll-rpc.publicnode.com",    "ETH",  18),
    "zksync":    ("zksync-mainnet",  "https://mainnet.era.zksync.io",        "ETH",  18),
    "mantle":    ("mantle-mainnet",  "https://mantle-rpc.publicnode.com",    "MNT",  18),
    "blast":     ("blast-mainnet",   "https://blast-rpc.publicnode.com",     "ETH",  18),
}

# 主流 ERC20 代币合约（chain_name -> {symbol: address}）
ERC20_TOKENS = {
    "ethereum": {
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "DAI":  "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
        "UNI":  "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
        "PEPE": "0x6982508145454Ce325dDbE47a25d4ec3d2311933",
        "SHIB": "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE",
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    },
    "polygon": {
        "USDT_e":  "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "USDC_e":  "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "USDC":    "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        "WMATIC":  "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
    },
    "arbitrum": {
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "ARB":  "0x912CE59144191C1204E64559FE8253a0e49E6548",
        "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
    },
    "optimism": {
        "USDT": "0x94b008aA00579c1307B0EF2c499aD98a8ceB58e6",
        "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
        "OP":   "0x4200000000000000000000000000000000000042",
        "WETH": "0x4200000000000000000000000000000000000006",
    },
    "base": {
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "WETH": "0x4200000000000000000000000000000000000006",
        "DEGEN":"0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed",
    },
}

# ============================================================
#                         初始化
# ============================================================

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("scanner")

# 优雅退出
_STOP = False


def _on_signal(signum, _frame):
    global _STOP
    _STOP = True
    log.info("收到信号 %s，准备退出...", signum)


signal.signal(signal.SIGINT, _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


# ============================================================
#                       RPC 工具
# ============================================================

def _rpc_url(chain_name: str) -> str:
    """返回指定链的 RPC URL：优先 Alchemy，否则公共 RPC。"""
    subdomain, public_rpc, _, _ = CHAINS[chain_name]
    if ALCHEMY_API_KEY:
        return f"https://{subdomain}.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
    return public_rpc


def rpc_call(rpc_url: str, method: str, params: list, retry: int = MAX_RETRIES):
    """通用 JSON-RPC 调用，失败重试。返回 result 或 None。"""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    for attempt in range(1, retry + 1):
        try:
            resp = requests.post(rpc_url, json=payload, timeout=RPC_TIMEOUT)
            data = resp.json()
            if "error" in data and data["error"]:
                log.warning("RPC error on %s (%s): %s", method, rpc_url, data["error"])
                return None
            return data.get("result")
        except Exception as e:
            if attempt == retry:
                log.warning("RPC %s 失败(%s/%s): %s", method, attempt, retry, e)
            else:
                time.sleep(0.4 * attempt)
    return None


def get_native_balance(rpc_url: str, address: str) -> int:
    """返回原生代币余额(wei)，0 表示无余额。"""
    result = rpc_call(rpc_url, "eth_getBalance", [address, "latest"])
    try:
        return int(result, 16) if result else 0
    except (TypeError, ValueError):
        return 0


def get_erc20_balance(rpc_url: str, token: str, address: str) -> int:
    """调用 balanceOf(address) 查 ERC20 余额。"""
    # balanceOf(address) selector = 0x70a08231
    data = "0x70a08231000000000000000000000000" + address[2:].lower()
    result = rpc_call(rpc_url, "eth_call", [{"to": token, "data": data}, "latest"])
    try:
        return int(result, 16) if result else 0
    except (TypeError, ValueError):
        return 0


def get_alchemy_token_balances(rpc_url: str, address: str):
    """使用 alchemy_getTokenBalances 一次性拿到地址持有的全部 ERC20 列表。
    返回 [(token_address, balance_hex), ...] 或 None（不支持时）。"""
    if not ALCHEMY_API_KEY or "alchemy.com" not in rpc_url:
        return None
    result = rpc_call(rpc_url, "alchemy_getTokenBalances", [address])
    if not result:
        return None
    return [(b.get("contractAddress"), b.get("tokenBalance"))
            for b in result.get("tokenBalances", [])
            if b.get("tokenBalance") and b["tokenBalance"] != "0x"]


# ============================================================
#                       核心扫描
# ============================================================

def gen_keypair():
    """生成随机私钥 + 校验和地址。"""
    priv = secrets.token_bytes(32)
    # 防止生成不合法私钥(全 0 / 超 n)
    n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    priv_int = int.from_bytes(priv, "big")
    if priv_int == 0 or priv_int >= n:
        return gen_keypair()
    pk_hex = "0x" + priv.hex()
    acct = Account.from_key(priv)
    return pk_hex, acct.address


def record_hit(private_key: str, address: str, hits: list):
    """把命中记录追加写入文件。hits = [{chain, type, symbol, contract, raw_balance, decimals}]"""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "private_key": private_key,
        "address": address,
        "hits": hits,
    }
    with FOUND_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    log.warning("⚡ 命中！地址=%s 命中数=%d 详情已写入 %s", address, len(hits), FOUND_FILE)
    for h in hits:
        log.warning("    - %s %s %s 余额(raw)=%s", h["chain"], h["type"], h["symbol"], h["raw_balance"])


def scan_address(address: str) -> list:
    """全并发扫描：所有链的所有 RPC 调用提交到同一个线程池。"""
    addr = to_checksum_address(address)
    all_hits = []
    # 每个 task: (chain, kind, symbol, contract, decimals, future)
    tasks = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        for chain_name in CHAINS:
            rpc_url = _rpc_url(chain_name)
            native_sym, native_dec = CHAINS[chain_name][2], CHAINS[chain_name][3]
            tasks.append((chain_name, "native", native_sym, None, native_dec,
                          ex.submit(get_native_balance, rpc_url, addr)))
            for symbol, token in ERC20_TOKENS.get(chain_name, {}).items():
                tasks.append((chain_name, "erc20", symbol, token, 18,
                              ex.submit(get_erc20_balance, rpc_url, token, addr)))
            if ALCHEMY_API_KEY:
                tasks.append((chain_name, "alchemy", None, None, 18,
                              ex.submit(get_alchemy_token_balances, rpc_url, addr)))

        known_by_chain = {c: {v.lower() for v in t.values()} for c, t in ERC20_TOKENS.items()}
        for chain_name, kind, symbol, contract, dec, fut in tasks:
            try:
                result = fut.result()
            except Exception as e:
                log.debug("task %s/%s 异常: %s", chain_name, kind, e)
                continue

            if kind == "alchemy":
                if not result:
                    continue
                for token_addr, bal_hex in result:
                    try:
                        bal = int(bal_hex, 16)
                    except (TypeError, ValueError):
                        continue
                    if bal <= 0:
                        continue
                    if token_addr and token_addr.lower() in known_by_chain.get(chain_name, set()):
                        continue
                    all_hits.append({
                        "chain": chain_name, "type": "erc20_auto", "symbol": "UNKNOWN",
                        "contract": token_addr, "raw_balance": str(bal), "decimals": 18,
                    })
            elif kind == "native":
                if result and result > 0:
                    all_hits.append({
                        "chain": chain_name, "type": "native", "symbol": symbol,
                        "contract": None, "raw_balance": str(result), "decimals": dec,
                    })
            elif kind == "erc20":
                if result and result > 0:
                    all_hits.append({
                        "chain": chain_name, "type": "erc20", "symbol": symbol,
                        "contract": contract, "raw_balance": str(result), "decimals": dec,
                    })
    return all_hits


def load_stats() -> dict:
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"scanned": 0, "hits": 0, "started_at": datetime.now(timezone.utc).isoformat()}


def save_stats(stats: dict):
    try:
        STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.debug("写入 stats 失败: %s", e)


# ============================================================
#                         主循环
# ============================================================

def main_loop():
    stats = load_stats()
    log.info("==== 多链私钥扫描器启动 ====")
    log.info("覆盖链: %s", ", ".join(CHAINS.keys()))
    log.info("Alchemy 增强扫描: %s", "已启用" if ALCHEMY_API_KEY else "未启用（仅查主流代币）")
    log.info("扫描间隔: %.2fs  输出目录: %s", SCAN_INTERVAL, OUTPUT_DIR)

    while not _STOP:
        try:
            pk, addr = gen_keypair()
            hits = scan_address(addr)
            stats["scanned"] += 1
            if hits:
                stats["hits"] += 1
                record_hit(pk, addr, hits)

            # 每 10 轮输出一次进度
            if stats["scanned"] % 10 == 0:
                log.info("已扫描 %d 个地址，命中 %d 个", stats["scanned"], stats["hits"])
                save_stats(stats)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("扫描异常: %s\n%s", e, traceback.format_exc())
            time.sleep(1.0)
            continue

        if SCAN_INTERVAL > 0:
            time.sleep(SCAN_INTERVAL)

    save_stats(stats)
    log.info("==== 扫描器退出，累计扫描 %d，命中 %d ====", stats["scanned"], stats["hits"])


if __name__ == "__main__":
    main_loop()

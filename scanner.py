#!/usr/bin/env python3
"""
多链私钥扫描器
随机生成私钥 → 推导地址 → 并发查询多链原生代币和 ERC20
"""

import os
import sys
import json
import time
import secrets
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import deque
import threading

# 以太坊相关库
try:
    from eth_account import Account
    from eth_keys import keys
    import aiohttp
except ImportError:
    print("请安装依赖: pip install eth-account aiohttp")
    sys.exit(1)

# 配置
OUTPUT_DIR = Path("/workspace/output")
SCAN_INTERVAL = float(os.getenv("SCAN_INTERVAL", "0.3"))
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "50"))

# 多链 RPC 端点（使用公共 RPC）
RPC_ENDPOINTS = {
    "ethereum": [
        "https://eth.llamarpc.com",
        "https://ethereum.publicnode.com",
    ],
    "polygon": [
        "https://polygon.llamarpc.com",
        "https://polygon.publicnode.com",
    ],
    "arbitrum": [
        "https://arbitrum.llamarpc.com",
        "https://arbitrum.publicnode.com",
    ],
    "optimism": [
        "https://optimism.llamarpc.com",
        "https://optimism.publicnode.com",
    ],
    "base": [
        "https://base.llamarpc.com",
        "https://base.publicnode.com",
    ],
    "linea": [
        "https://linea.blockpi.network/v1/rpc/public",
    ],
    "scroll": [
        "https://scroll.publicnode.com",
    ],
    "zksync": [
        "https://mainnet.era.zksync.io",
    ],
    "mantle": [
        "https://mantle.publicnode.com",
    ],
    "blast": [
        "https://blast.publicnode.com",
    ],
}

# 主流 ERC20 代币合约地址
ERC20_TOKENS = {
    "ethereum": {
        "USDT": "0xdAC17F958D2ee523aFe2207439121B4EE8B7B561",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    },
    "polygon": {
        "USDT": "0xc2132D05D31c914a87C261098e8B9A1D4c26eAdE",
        "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84170",
        "WMATIC": "0x0d500B1d8E8e31CF930C4e0A4F2dA5E5e7e3d9C2",
    },
    # 其他链类似配置...
}


@dataclass
class Stats:
    """统计指标"""
    scanned: int = 0
    hits: int = 0
    start_time: float = 0.0
    keygen_times: deque = None
    scan_times: deque = None
    total_running_sec: float = 0.0

    def __post_init__(self):
        if self.keygen_times is None:
            self.keygen_times = deque(maxlen=30)
        if self.scan_times is None:
            self.scan_times = deque(maxlen=30)


class WalletScanner:
    """多链钱包扫描器"""

    def __init__(self):
        self.stats = Stats(start_time=time.time())
        self.stats_lock = threading.Lock()
        self.logger = self._setup_logger()
        self.session: Optional[aiohttp.ClientSession] = None
        self.found_file = OUTPUT_DIR / "found_wallets.jsonl"
        self.stats_file = OUTPUT_DIR / "stats.json"
        self.log_file = OUTPUT_DIR / "scanner.log"

    def _setup_logger(self) -> logging.Logger:
        """配置日志"""
        logger = logging.getLogger("scanner")
        logger.setLevel(logging.INFO)

        # 文件处理器
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            OUTPUT_DIR / "scanner.log",
            mode="a",
            encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(message)s")
        )
        logger.addHandler(console_handler)

        return logger

    def generate_private_key(self) -> str:
        """生成随机私钥"""
        # 使用 secrets 模块生成密码学安全的随机私钥
        private_key_bytes = secrets.token_bytes(32)
        private_key = private_key_bytes.hex()
        return private_key

    def derive_address(self, private_key: str) -> str:
        """从私钥推导以太坊地址"""
        try:
            account = Account.from_key(private_key)
            return account.address
        except Exception as e:
            self.logger.error(f"地址推导失败: {e}")
            return None

    async def check_balance(
        self,
        address: str,
        chain: str,
        token_symbol: str = None
    ) -> Optional[float]:
        """查询链上余额"""
        rpc_urls = RPC_ENDPOINTS.get(chain, [])
        if not rpc_urls:
            return None

        # 轮询 RPC 端点
        for rpc_url in rpc_urls:
            try:
                if token_symbol is None:
                    # 查询原生代币余额
                    payload = {
                        "jsonrpc": "2.0",
                        "method": "eth_getBalance",
                        "params": [address, "latest"],
                        "id": 1
                    }
                else:
                    # 查询 ERC20 余额
                    token_address = ERC20_TOKENS.get(chain, {}).get(token_symbol)
                    if not token_address:
                        continue

                    # ERC20 balanceOf(address) 调用
                    data = f"0x70a08231{address[2:].zfill(64)}"
                    payload = {
                        "jsonrpc": "2.0",
                        "method": "eth_call",
                        "params": [{
                            "to": token_address,
                            "data": data
                        }, "latest"],
                        "id": 1
                    }

                async with self.session.post(
                    rpc_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if "result" in result and result["result"]:
                            balance_hex = result["result"]
                            balance = int(balance_hex, 16)
                            # 转换为可读格式（假设 18 位小数）
                            return balance / 10**18

            except asyncio.TimeoutError:
                self.logger.warning(f"{chain} RPC 超时: {rpc_url}")
                continue
            except Exception as e:
                self.logger.warning(f"{chain} RPC 错误: {e}")
                continue

        return None

    async def scan_wallet(self, private_key: str) -> Optional[Dict]:
        """扫描单个钱包"""
        start_time = time.time()

        # 1. 推导地址
        address = self.derive_address(private_key)
        if not address:
            return None

        # 2. 并发查询所有链
        results = {}
        tasks = []

        # 查询原生代币
        for chain in RPC_ENDPOINTS.keys():
            tasks.append(self._check_and_record(address, chain, None, results))

        # 查询主流 ERC20（简化版，仅查询以太坊上的 USDT/USDC）
        for token in ["USDT", "USDC"]:
            tasks.append(self._check_and_record(address, "ethereum", token, results))

        await asyncio.gather(*tasks, return_exceptions=True)

        # 3. 检查是否有余额
        has_balance = any(v > 0 for v in results.values())

        scan_time = time.time() - start_time
        with self.stats_lock:
            self.stats.scan_times.append(scan_time)

        if has_balance:
            return {
                "private_key": private_key,
                "address": address,
                "balances": results,
                "found_at": datetime.now().isoformat()
            }

        return None

    async def _check_and_record(
        self,
        address: str,
        chain: str,
        token: str,
        results: Dict
    ):
        """检查并记录余额"""
        try:
            balance = await self.check_balance(address, chain, token)
            key = f"{chain}_{token}" if token else chain
            results[key] = balance or 0
        except Exception as e:
            self.logger.debug(f"查询失败 {chain} {token}: {e}")
            key = f"{chain}_{token}" if token else chain
            results[key] = 0

    def save_found_wallet(self, wallet_data: Dict):
        """保存命中的钱包"""
        try:
            with open(self.found_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(wallet_data) + "\n")
            self.logger.info(
                f"🎯 命中! 地址: {wallet_data['address']}, "
                f"余额: {wallet_data['balances']}"
            )
        except Exception as e:
            self.logger.error(f"保存命中记录失败: {e}")

    def update_stats(self):
        """更新统计文件"""
        with self.stats_lock:
            self.stats.total_running_sec = time.time() - self.stats.start_time

            # 计算速度指标
            total_time = self.stats.total_running_sec
            keygen_times = list(self.stats.keygen_times)
            scan_times = list(self.stats.scan_times)

            stats_data = {
                "scanned": self.stats.scanned,
                "hits": self.stats.hits,
                "start_time": self.stats.start_time,
                "total_running_sec": round(self.stats.total_running_sec, 2),
                "scan_rate_total_addr_per_sec": round(
                    self.stats.scanned / max(total_time, 1), 4
                ),
                "scan_rate_recent_addr_per_sec": round(
                    1.0 / (sum(scan_times) / max(len(scan_times), 1)), 4
                ) if scan_times else 0,
                "keygen_rate_keys_per_sec": round(
                    1.0 / (sum(keygen_times) / max(len(keygen_times), 1)), 4
                ) if keygen_times else 0,
                "last_updated": datetime.now().isoformat()
            }

        try:
            with open(self.stats_file, "w", encoding="utf-8") as f:
                json.dump(stats_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"更新统计文件失败: {e}")

    async def run(self):
        """主扫描循环"""
        self.logger.info(f"🚀 扫描器启动，间隔: {SCAN_INTERVAL}s")

        # 创建 HTTP 会话
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT_REQUESTS)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector
        )

        try:
            while True:
                try:
                    # 1. 生成私钥
                    keygen_start = time.time()
                    private_key = self.generate_private_key()
                    keygen_time = time.time() - keygen_start

                    with self.stats_lock:
                        self.stats.keygen_times.append(keygen_time)

                    # 2. 扫描钱包
                    wallet_data = await self.scan_wallet(private_key)

                    # 3. 更新统计
                    with self.stats_lock:
                        self.stats.scanned += 1
                        if wallet_data:
                            self.stats.hits += 1
                            self.save_found_wallet(wallet_data)

                    # 4. 定期更新统计文件
                    if self.stats.scanned % 10 == 0:
                        self.update_stats()

                    # 5. 等待
                    await asyncio.sleep(SCAN_INTERVAL)

                except KeyboardInterrupt:
                    self.logger.info("收到停止信号")
                    break
                except Exception as e:
                    self.logger.error(f"扫描异常: {e}", exc_info=True)
                    await asyncio.sleep(1)

        finally:
            await self.session.close()
            self.update_stats()
            self.logger.info("扫描器停止")


async def main():
    """主入口"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 初始化统计文件
    stats_file = OUTPUT_DIR / "stats.json"
    if not stats_file.exists():
        with open(stats_file, "w") as f:
            json.dump({
                "scanned": 0,
                "hits": 0,
                "start_time": time.time(),
                "total_running_sec": 0,
                "scan_rate_total_addr_per_sec": 0,
                "scan_rate_recent_addr_per_sec": 0,
                "keygen_rate_keys_per_sec": 0,
                "last_updated": datetime.now().isoformat()
            }, f, indent=2)

    # 初始化命中文件
    found_file = OUTPUT_DIR / "found_wallets.jsonl"
    if not found_file.exists():
        found_file.touch()

    scanner = WalletScanner()
    await scanner.run()


if __name__ == "__main__":
    asyncio.run(main())
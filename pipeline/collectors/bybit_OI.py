"""
Collector Bybit WebSocket robuste (reconnect/backoff)
Prod-safe, asynchrone, testable
"""
import asyncio
import json
from collections.abc import Callable
from typing import Any

import requests
import structlog
import websockets
from prometheus_client import Counter, Summary

log = structlog.get_logger()
BYBIT_OI_LATENCY = Summary('bybit_oi_latency_seconds', 'Latency of Bybit OI API calls')
BYBIT_OI_ERRORS = Counter('bybit_oi_errors_total', 'Total Bybit OI API errors')
BYBIT_OI_SUCCESS = Counter('bybit_oi_success_total', 'Total Bybit OI API successes')

class BybitWSCollector:
    """Collecteur Bybit WebSocket avec reconnexion et backoff."""
    WS_URL = "wss://stream.bybit.com/v5/public/linear"

    def __init__(self, symbol: str = "BTCUSDT", on_message: Callable | None = None):
        self.symbol = symbol
        self.on_message = on_message
        self.running = True
        self.backoff = 1

    async def connect(self):
        while self.running:
            try:
                async with websockets.connect(self.WS_URL) as ws:
                    sub_msg = json.dumps({
                        "op": "subscribe",
                        "args": [f"publicTrade.{self.symbol}"]
                    })
                    await ws.send(sub_msg)
                    self.backoff = 1
                    while self.running:
                        msg = await ws.recv()
                        if self.on_message:
                            self.on_message(json.loads(msg))
            except Exception as e:
                print(f"WS error: {e}, reconnect in {self.backoff}s...")
                await asyncio.sleep(self.backoff)
                self.backoff = min(self.backoff * 2, 60)

    def stop(self):
        self.running = False

    @BYBIT_OI_LATENCY.time()
    def fetch_bybit_oi(symbol: str) -> dict[str, Any] | None:
        """
        Fetch open interest and funding rate from Bybit.

        Parameters
        ----------
        symbol : str

        Returns
        -------
        Optional[Dict[str, Any]]
        """
        url = f"https://api.bybit.com/v5/market/open-interest?category=linear&symbol={symbol}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            BYBIT_OI_SUCCESS.inc()
            log.info("bybit_oi_success", symbol=symbol)
            return data
        except Exception as e:
            BYBIT_OI_ERRORS.inc()
            log.error("bybit_oi_error", symbol=symbol, error=str(e))
            return None

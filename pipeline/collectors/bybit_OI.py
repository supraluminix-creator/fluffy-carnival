"""
Collector Bybit WebSocket robuste (reconnect/backoff)
Prod-safe, asynchrone, testable
"""
import asyncio
import json
from collections.abc import Callable
from typing import Any, TypedDict, cast

import requests
import structlog
import websockets
from prometheus_client import Counter, Summary

log = structlog.get_logger()
BYBIT_OI_LATENCY = Summary('bybit_oi_latency_seconds', 'Latency of Bybit OI API calls')
BYBIT_OI_ERRORS = Counter('bybit_oi_errors_total', 'Total Bybit OI API errors')
BYBIT_OI_SUCCESS = Counter('bybit_oi_success_total', 'Total Bybit OI API successes')


class BybitOIRecord(TypedDict):
    """Normalized Open Interest record from Bybit REST API.

    Fields
    ------
    symbol: Trading symbol (e.g. BTCUSDT)
    open_interest: Open interest as float
    timestamp: Milliseconds epoch timestamp provided by Bybit
    """
    symbol: str
    open_interest: float
    timestamp: int

class BybitWSCollector:
    """Collecteur Bybit WebSocket avec reconnexion et backoff."""
    WS_URL = "wss://stream.bybit.com/v5/public/linear"

    def __init__(self, symbol: str = "BTCUSDT", on_message: Callable | None = None):
        self.symbol = symbol
        self.on_message = on_message
        self.running = True
        self.backoff = 1

    async def connect(self) -> None:
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

    def stop(self) -> None:
        self.running = False

    @staticmethod
    @BYBIT_OI_LATENCY.time()
    def fetch_bybit_oi(symbol: str) -> BybitOIRecord | None:
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
            data_obj = resp.json()
            if not isinstance(data_obj, dict):
                return None
            result = data_obj.get("result")
            if not isinstance(result, dict):
                return None
            list_data = result.get("list")
            if not isinstance(list_data, list) or not list_data:
                return None
            first = list_data[0]
            if not isinstance(first, dict):
                return None
            # Normalize expected keys; examples from Bybit docs
            symbol_val = first.get("symbol")
            oi_raw = first.get("openInterest")
            ts_raw = first.get("timestamp") or first.get("ts")
            try:
                if symbol_val is None or oi_raw is None or ts_raw is None:
                    return None
                open_interest = float(oi_raw)
                ts_int = int(ts_raw)
            except (ValueError, TypeError):
                return None
            record: BybitOIRecord = {
                "symbol": str(symbol_val),
                "open_interest": open_interest,
                "timestamp": ts_int,
            }
            BYBIT_OI_SUCCESS.inc()
            log.info("bybit_oi_success", symbol=symbol)
            return record
        except Exception as e:
            BYBIT_OI_ERRORS.inc()
            log.error("bybit_oi_error", symbol=symbol, error=str(e))
            return None

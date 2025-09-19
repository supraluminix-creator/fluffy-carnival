"""
Collector transaction count (on-chain)
Prod-safe, modulaire, testable
"""
from typing import Any, TypedDict, cast

import diskcache
import httpx
import requests  # type: ignore[import-untyped]
import structlog
from prometheus_client import Counter, Summary
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()
TXCOUNT_LATENCY = Summary('txcount_latency_seconds', 'Latency of TxCount API calls')
TXCOUNT_ERRORS = Counter('txcount_errors_total', 'Total TxCount API errors')
TXCOUNT_SUCCESS = Counter('txcount_success_total', 'Total TxCount API successes')

class TxCountData(TypedDict, total=False):
    symbol: str
    txcount: int


class TxCountCollector:
    """Collecteur nombre de transactions on-chain."""
    BASE_URL = "https://api.blockchain.info/charts/n-transactions"
    _cache_ttl = 300  # 5 min
    _disk_cache: diskcache.Cache = diskcache.Cache(".cache_txcount")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
    async def fetch_txcount_async(self, symbol: str = "BTC") -> dict[str, Any] | None:
        cache_key = f"txcount:{symbol}"
        cached = self._disk_cache.get(cache_key)
        if isinstance(cached, dict):
            return cast(dict[str, Any], cached)
        params = {"timespan": "1days", "format": "json"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            data = cast(dict[str, Any], resp.json())
        self._disk_cache.set(cache_key, data, expire=self._cache_ttl)
        return data

    @TXCOUNT_LATENCY.time()
    def fetch_txcount(self, symbol: str = "BTC") -> dict[str, Any] | None:
        """
        Wrapper sync pour compatibilité legacy/tests
        """
        try:
            url = "https://api.blockchain.info/q/getblockcount"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            blockcount = int(resp.text)
            TXCOUNT_SUCCESS.inc()
            log.info("txcount_success", symbol=symbol, blockcount=blockcount)
            result: dict[str, Any] = {"symbol": symbol, "txcount": blockcount}
            return result
        except Exception as e:
            log.error("txcount_main_error", symbol=symbol, error=str(e))
            # Fallback Etherscan (mock, à compléter avec clé API)
            try:
                # url = f"https://api.etherscan.io/api?...&apikey=YOUR_API_KEY"
                # resp = requests.get(url, timeout=10)
                # resp.raise_for_status()
                # data = resp.json()
                # txcount = data["result"]
                # TXCOUNT_SUCCESS.inc()
                # log.info("txcount_fallback_success", symbol=symbol, txcount=txcount)
                # return {"symbol": symbol, "txcount": txcount}
                raise NotImplementedError("Fallback Etherscan non implémenté")
            except Exception as e2:
                TXCOUNT_ERRORS.inc()
                log.error("txcount_fallback_error", symbol=symbol, error=str(e2))
                return None

"""
Collector hashrate (on-chain)
Prod-safe, modulaire, testable
"""
import asyncio
from typing import Any

import diskcache
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class HashrateCollector:
    """Collecteur hashrate on-chain."""
    BASE_URL = "https://api.blockchain.info/charts/hash-rate"
    _cache_ttl = 300  # 5 min
    _disk_cache = diskcache.Cache(".cache_hashrate")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
    async def fetch_hashrate_async(self, symbol: str = "BTC") -> dict[str, Any] | None:
        cache_key = f"hashrate:{symbol}"
        cached = self._disk_cache.get(cache_key)
        if cached is not None:
            return cached
        params = {"timespan": "1days", "format": "json"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        self._disk_cache.set(cache_key, data, expire=self._cache_ttl)
        return data

    def fetch_hashrate(self, symbol: str = "BTC") -> dict[str, Any] | None:
        """
        Wrapper sync pour compatibilité legacy/tests
        """
        try:
            return asyncio.run(self.fetch_hashrate_async(symbol))
        except Exception as e:
            print(f"Erreur Hashrate: {e}")
            return None

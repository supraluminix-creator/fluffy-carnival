"""Hashrate collector (on-chain).

Provides an async + sync API for retrieving network hashrate data.
The upstream endpoint (blockchain.info) returns a JSON structure similar to:

{
  "status": "ok",
  "name": "Hash rate",
  "unit": "Hash/s",
  "period": "day",
  "values": [ {"x": 1726070400, "y": 529384739245.23}, ... ]
}

We model this response via TypedDicts so mypy can validate usage while
remaining resilient to extra keys (non-total).
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict, cast

import diskcache
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class _ChartValue(TypedDict):
    x: int  # Unix timestamp
    y: float  # Hashrate value (unit depends on upstream - usually Hash/s)


class HashrateResponse(TypedDict, total=False):  # Non-total: tolerate extra / missing optional keys
    status: str
    name: str
    unit: str
    period: str
    description: str
    values: list[_ChartValue]


# Public alias for readability in signatures
HashrateData = HashrateResponse


class HashrateCollector:
    """Collecteur hashrate on-chain."""

    BASE_URL = "https://api.blockchain.info/charts/hash-rate"
    _cache_ttl: int = 300  # 5 min
    _disk_cache: diskcache.Cache = diskcache.Cache(".cache_hashrate")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
    async def fetch_hashrate_async(self, symbol: str = "BTC") -> HashrateData | None:
        """Fetch hashrate data (async).

        Parameters
        ----------
        symbol: str
            Network symbol (currently only BTC endpoint supported, retained for future extensibility).
        Returns
        -------
        HashrateData | None
            Parsed response on success, else None.
        """
        cache_key = f"hashrate:{symbol}"
        cached = self._disk_cache.get(cache_key)
        if isinstance(cached, dict):  # Defensive: ensure shape before casting
            return cast(HashrateData, cached)

        params = {"timespan": "1days", "format": "json"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                raw = resp.json()
        except Exception:
            return None

        if not isinstance(raw, dict):  # Unexpected shape
            return None

        data = cast(HashrateData, raw)
        # Cache only dict payloads to avoid storing invalid shapes
        self._disk_cache.set(cache_key, data, expire=self._cache_ttl)
        return data

    def fetch_hashrate(self, symbol: str = "BTC") -> HashrateData | None:
        """Sync wrapper for legacy/test contexts.

        Wraps the async method with asyncio.run while swallowing exceptions to return None
        (mirrors existing resilience pattern across collectors).
        """
        try:
            return asyncio.run(self.fetch_hashrate_async(symbol))
        except Exception:
            return None

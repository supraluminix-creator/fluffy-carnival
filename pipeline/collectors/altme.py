"""
Collector Altme (identity, KYC, etc.)
Prod-safe, modulaire, testable
"""
import asyncio
from typing import Any

import diskcache
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class AltmeCollector:
    """Collecteur Altme (identity, KYC, etc.)."""
    BASE_URL = "https://api.altme.io/v1/kyc"
    _cache_ttl = 300  # 5 min
    _disk_cache = diskcache.Cache(".cache_altme")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
    async def fetch_kyc_async(self, user_id: str) -> dict[str, Any] | None:
        cache_key = f"kyc:{user_id}"
        cached = self._disk_cache.get(cache_key)
        if cached is not None:
            return cached
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.BASE_URL}/{user_id}")
            resp.raise_for_status()
            data = resp.json()
        self._disk_cache.set(cache_key, data, expire=self._cache_ttl)
        return data

    def fetch_kyc(self, user_id: str) -> dict[str, Any] | None:
        """
        Wrapper sync pour compatibilité legacy/tests
        """
        try:
            return asyncio.run(self.fetch_kyc_async(user_id))
        except Exception as e:
            print(f"Erreur Altme: {e}")
            return None

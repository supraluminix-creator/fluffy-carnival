"""Altme collector (identity / KYC).

Adds a typed interface over Altme's KYC endpoint. The expected (illustrative)
JSON payload might resemble:

{
  "userId": "abc123",
  "kycStatus": "APPROVED",
  "country": "FR",
  "updatedAt": "2024-09-01T10:23:45Z"
}

We keep the schema flexible (non-total) to tolerate additional fields.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict, cast

import diskcache
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class KYCRecord(TypedDict, total=False):
    userId: str
    kycStatus: str  # e.g. PENDING / APPROVED / REJECTED
    country: str
    updatedAt: str  # ISO8601
    reason: str  # optional rejection reason


KYCData = KYCRecord


class AltmeCollector:
    """Collecteur Altme (identity, KYC, etc.)."""

    BASE_URL = "https://api.altme.io/v1/kyc"
    _cache_ttl: int = 300  # 5 min
    _disk_cache: diskcache.Cache = diskcache.Cache(".cache_altme")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
    async def fetch_kyc_async(self, user_id: str) -> KYCData | None:
        """Fetch KYC data (async).

        Returns None on network / validation failure.
        """
        cache_key = f"kyc:{user_id}"
        cached = self._disk_cache.get(cache_key)
        if isinstance(cached, dict):
            return cast(KYCData, cached)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.BASE_URL}/{user_id}")
                resp.raise_for_status()
                raw = resp.json()
        except Exception:
            return None

        if not isinstance(raw, dict):
            return None
        data = cast(KYCData, raw)
        self._disk_cache.set(cache_key, data, expire=self._cache_ttl)
        return data

    def fetch_kyc(self, user_id: str) -> KYCData | None:
        """Sync wrapper for tests / legacy flows."""
        try:
            return asyncio.run(self.fetch_kyc_async(user_id))
        except Exception:
            return None

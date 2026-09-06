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
import os
from contextlib import suppress
from typing import TypedDict, cast

import diskcache
import httpx
import structlog
from prometheus_client import REGISTRY as PROM_REGISTRY
from prometheus_client import Counter
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.flags import is_dry_run_facade, is_forced_facade
from pipeline.http import async_fetch_json
from pipeline.metrics.collectors import mark_legacy_http, set_facade_mode


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

    # Compteur usage HTTP legacy (idempotent)
    try:  # pragma: no cover - idempotent
        LEGACY_HTTP_USAGE = Counter("legacy_http_usage_total", "Legacy HTTP usage by collector", ["collector"])
    except ValueError as exc:  # déjà enregistré
        existing = PROM_REGISTRY._names_to_collectors.get("legacy_http_usage_total")  # type: ignore[attr-defined]
        if existing is None:
            raise RuntimeError("legacy_http_usage_total counter missing from registry") from exc
        LEGACY_HTTP_USAGE = cast(Counter, existing)
    with suppress(Exception):  # pragma: no cover - initialise l'échantillon
        LEGACY_HTTP_USAGE.labels(collector="altme")
    _LEGACY_LOGGED = False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
    async def fetch_kyc_async(self, user_id: str) -> KYCData | None:
        """Fetch KYC data (async).

        Returns None on network / validation failure.
        """
        cache_key = f"kyc:{user_id}"
        cached = self._disk_cache.get(cache_key)
        if isinstance(cached, dict):
            return cast(KYCData, cached)

        force_facade = is_forced_facade()
        dry_run = is_dry_run_facade() and not force_facade
        with suppress(Exception):  # pragma: no cover
            set_facade_mode("altme", force_facade, dry_run)

        retry_enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
        url = f"{self.BASE_URL}/{user_id}"
        try:
            if retry_enabled or force_facade:
                # Utilise la façade (retry/breaker unifiés) avec client fourni (pooling/compat tests)
                async with httpx.AsyncClient(timeout=10) as client:
                    raw = await async_fetch_json(url, timeout=10, client=client)
            else:
                # Chemin legacy direct (instrumenté) pour compatibilité progressive
                try:
                    mark_legacy_http("altme")
                    if not self._LEGACY_LOGGED:
                        structlog.get_logger().info("legacy_http_usage_detected", collector="altme")
                        self._LEGACY_LOGGED = True
                except Exception:  # pragma: no cover
                    pass
                async with httpx.AsyncClient(timeout=10) as client:
                    # Uniformize through facade to standardize error handling and metrics
                    raw = await async_fetch_json(url, timeout=10, client=client)
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

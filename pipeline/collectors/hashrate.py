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
import os
from contextlib import suppress
from typing import TypedDict, cast

import diskcache
import httpx
from prometheus_client import REGISTRY as PROM_REGISTRY
from prometheus_client import Counter
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.flags import is_dry_run_facade, is_forced_facade
from pipeline.http import async_fetch_json
from pipeline.metrics import FACADE_FORCED_LEAK
from pipeline.metrics.collectors import mark_legacy_http, set_facade_mode

# Compteur legacy (idempotent) partagé
try:  # pragma: no cover - idempotent
    LEGACY_HTTP_USAGE = Counter("legacy_http_usage_total", "Legacy HTTP usage by collector", ["collector"])
except ValueError as exc:  # déjà défini
    existing = PROM_REGISTRY._names_to_collectors.get("legacy_http_usage_total")  # type: ignore[attr-defined]
    if existing is None:
        raise RuntimeError("legacy_http_usage_total counter missing from registry") from exc
    LEGACY_HTTP_USAGE = cast(Counter, existing)
with suppress(Exception):  # pragma: no cover - pré-initialise sample
    LEGACY_HTTP_USAGE.labels(collector="onchain_hashrate")  # type: ignore[call-arg]
_LEGACY_LOGGED = False


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

        force_facade = is_forced_facade()
        dry_run = is_dry_run_facade() and not force_facade
        with suppress(Exception):  # pragma: no cover
            set_facade_mode("onchain_hashrate", force_facade, dry_run)
        params = {"timespan": "1days", "format": "json"}
        try:
            retry_enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
            if retry_enabled or force_facade:
                # utilisation façade (retry centralisé) avec client fourni (pooling/compat tests)
                async with httpx.AsyncClient(timeout=10) as client:
                    raw = await async_fetch_json(self.BASE_URL, params=params, timeout=10, client=client)
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    try:
                        mark_legacy_http("onchain_hashrate")
                        global _LEGACY_LOGGED
                        if not _LEGACY_LOGGED:
                            import structlog

                            structlog.get_logger().info("legacy_http_usage_detected", collector="onchain_hashrate")
                            _LEGACY_LOGGED = True
                    except Exception:  # pragma: no cover
                        pass
                    resp = await client.get(self.BASE_URL, params=params)
                    resp.raise_for_status()
                    raw = resp.json()
        except Exception:
            if force_facade:
                # Pas de repli legacy en mode forced pour cohérence métriques
                with suppress(Exception):  # leak gauge set si on détecte tentative legacy (ici on ne tente pas)
                    FACADE_FORCED_LEAK.labels(collector="onchain_hashrate").set(0)  # type: ignore[attr-defined]
                return None
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
        force_facade = is_forced_facade()
        dry_run = is_dry_run_facade() and not force_facade
        with suppress(Exception):  # pragma: no cover
            set_facade_mode("onchain_hashrate", force_facade, dry_run)
        try:
            return asyncio.run(self.fetch_hashrate_async(symbol))
        except Exception:
            return None

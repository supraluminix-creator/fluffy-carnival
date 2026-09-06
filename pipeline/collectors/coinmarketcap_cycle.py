"""CoinMarketCap – Crypto Market Cycle Indicators collector

Approche:
- Tentative API interne JSON (non documentée)
- Fallback: scraping dynamique du __NEXT_DATA__ (sans JS avec requests + parse HTML)
- Cache disque TTL 1h pour limiter la charge

Sortie normalisée:
[
    {
        "indicator": str,
        "status": str | None,
        "value": float | int | str | None,
        "thresholds": dict | None,
        "source": "api" | "scraper"
    },
    ...
]
"""

from __future__ import annotations

import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from diskcache import Cache

from pipeline.http import fetch_json

logger = structlog.get_logger(__name__)

API_URL = "https://api.coinmarketcap.com/data-api/v3/charts/crypto-market-cycle-indicators"
SCRAPE_URL = "https://coinmarketcap.com/charts/crypto-market-cycle-indicators/"


def _cache() -> Cache:
    return Cache(os.getenv("CMC_CYCLE_CACHE_DIR", ".cache"))


def _normalize(items: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    return [
        {
            "indicator": it.get("name") or it.get("indicator") or "",
            "status": it.get("status"),
            "value": it.get("value"),
            "thresholds": it.get("thresholds"),
            "source": source,
        }
        for it in items
    ]


def _fetch_api(timeout: float = 10.0) -> list[dict[str, Any]] | None:
    params = {"convert": "USD"}
    try:
        data = fetch_json(API_URL, params=params, timeout=timeout)
        items = (data or {}).get("data", {}).get("indicators")
        if isinstance(items, list) and items:
            return _normalize(items, source="api")
        return None
    except Exception as e:  # pragma: no cover - robust fallback
        logger.warning("cmc_cycle_api_error", error=str(e))
        return None


def _fetch_scrape(timeout: float = 15.0) -> list[dict[str, Any]] | None:
    """Fallback scraping: récupérer __NEXT_DATA__ et extraire les indicateurs."""
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get(SCRAPE_URL)
            if resp.status_code != 200:
                return None
            # Extraire le contenu de <script id="__NEXT_DATA__"> ... </script>
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL | re.IGNORECASE)
            if not m:
                return None
            data = json.loads(m.group(1))
            items = (
                data.get("props", {})
                .get("pageProps", {})
                .get("initialState", {})
                .get("charts", {})
                .get("cryptoMarketCycleIndicators", {})
                .get("data", {})
                .get("indicators")
            )
            if isinstance(items, list) and items:
                return _normalize(items, source="scraper")
            return None
    except Exception as e:  # pragma: no cover - robust fallback
        logger.warning("cmc_cycle_scrape_error", error=str(e))
        return None


@dataclass
class CMCCycleOptions:
    cache_ttl: int = 3600  # 1h
    timeout_api: float = 10.0
    timeout_scrape: float = 15.0


def fetch_cmc_cycle_indicators(opts: CMCCycleOptions | None = None) -> list[dict[str, Any]]:
    """Retourne la liste normalisée d’indicateurs de cycle.

    - Essaie l’API interne; si échec, fallback scraping.
    - Cache disque (diskcache) TTL 1h par défaut.
    """
    opts = opts or CMCCycleOptions()
    # Env overrides (sans casser opts explicites)
    try:
        env_ttl = int(os.getenv("CMC_CYCLE_CACHE_TTL", str(opts.cache_ttl)))
        opts.cache_ttl = env_ttl
    except Exception:
        pass
    disable_cache_read = os.getenv("CMC_CYCLE_CACHE_DISABLE", "0") == "1"
    key = "cmc_cycle_indicators_v1"
    cache = _cache()
    try:
        if (not disable_cache_read) and (key in cache):
            cached = cache.get(key, default=None)
            if isinstance(cached, list):
                return cached
    except Exception:  # pragma: no cover - lecture cache non critique
        pass

    items = _fetch_api(timeout=opts.timeout_api)
    if not items:
        items = _fetch_scrape(timeout=opts.timeout_scrape) or []

    with suppress(Exception):  # pragma: no cover - écriture cache non critique
        cache.set(key, items, expire=opts.cache_ttl)
    return items


__all__ = ["CMCCycleOptions", "fetch_cmc_cycle_indicators"]

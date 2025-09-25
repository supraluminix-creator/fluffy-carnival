"""
Collector transaction count (on-chain)
Prod-safe, modulaire, testable
"""
import asyncio
from contextlib import suppress
from typing import Any, TypedDict, cast

import diskcache
import httpx
import requests
import structlog
from prometheus_client import REGISTRY as PROM_REGISTRY
from prometheus_client import Counter, Summary
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.flags import is_dry_run_facade, is_forced_facade
from pipeline.http import async_fetch_json
from pipeline.instrumentation import instrument_collector
from pipeline.metrics.collectors import mark_legacy_http, set_facade_mode

# Legacy counter idempotent
try:
    LEGACY_HTTP_USAGE = Counter('legacy_http_usage_total', 'Legacy HTTP usage by collector', ['collector'])
except ValueError:  # déjà défini
    LEGACY_HTTP_USAGE = PROM_REGISTRY._names_to_collectors.get('legacy_http_usage_total')  # type: ignore[attr-defined]
with suppress(Exception):  # pragma: no cover
    LEGACY_HTTP_USAGE.labels(collector='onchain_txcount')  # type: ignore[call-arg]
_LEGACY_LOGGED = False

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
        force_facade = is_forced_facade()
        dry_run = is_dry_run_facade() and not force_facade
        with suppress(Exception):  # pragma: no cover
            set_facade_mode("onchain_txcount", force_facade, dry_run)
        params = {"timespan": "1days", "format": "json"}
        if force_facade:
            try:
                data = cast(dict[str, Any], await async_fetch_json(self.BASE_URL, params=params, timeout=10))
            except Exception:
                return None
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                try:
                    mark_legacy_http('onchain_txcount')
                    global _LEGACY_LOGGED
                    if not _LEGACY_LOGGED:
                        import structlog
                        structlog.get_logger().info('legacy_http_usage_detected', collector='onchain_txcount')
                        _LEGACY_LOGGED = True
                except Exception:  # pragma: no cover
                    pass
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                data = cast(dict[str, Any], resp.json())
        self._disk_cache.set(cache_key, data, expire=self._cache_ttl)
        return data

    @instrument_collector("txcount")
    @TXCOUNT_LATENCY.time()
    def fetch_txcount(self, symbol: str = "BTC") -> dict[str, Any] | None:
        """
        Wrapper sync pour compatibilité legacy/tests
        """
        force_facade = is_forced_facade()
        dry_run = is_dry_run_facade() and not force_facade
        with suppress(Exception):  # pragma: no cover
            set_facade_mode("onchain_txcount", force_facade, dry_run)
        if force_facade:
            # On réutilise le chemin async (déjà façadé) pour cohérence métriques; si erreur -> None
            try:
                data = asyncio.run(self.fetch_txcount_async(symbol))  # type: ignore[name-defined]
                if isinstance(data, dict) and 'txcount' in data:
                    TXCOUNT_SUCCESS.inc()
                    return {"symbol": symbol, "txcount": data.get('txcount')}
            except Exception:  # pragma: no cover
                return None
            return None
        # Chemin legacy
        try:
            url = "https://api.blockchain.info/q/getblockcount"
            try:
                mark_legacy_http('onchain_txcount')
                global _LEGACY_LOGGED
                if not _LEGACY_LOGGED:
                    import structlog
                    structlog.get_logger().info('legacy_http_usage_detected', collector='onchain_txcount')
                    _LEGACY_LOGGED = True
            except Exception:  # pragma: no cover
                pass
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            blockcount = int(resp.text)
            TXCOUNT_SUCCESS.inc()
            log.info("txcount_success", symbol=symbol, blockcount=blockcount)
            return {"symbol": symbol, "txcount": blockcount}
        except Exception as e:
            log.error("txcount_main_error", symbol=symbol, error=str(e))
            try:
                raise NotImplementedError("Fallback Etherscan non implémenté")
            except Exception as e2:
                TXCOUNT_ERRORS.inc()
                log.error("txcount_fallback_error", symbol=symbol, error=str(e2))
                return None

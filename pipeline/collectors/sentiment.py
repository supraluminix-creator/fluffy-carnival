"""
Collector Sentiment (Alternative.me, TokenMetrics, etc.)
Prod-safe, async, retry/backoff, cache TTL, fallback
"""

from contextlib import suppress
from typing import TypedDict

import httpx
import structlog
from diskcache import Cache
from prometheus_client import REGISTRY as PROM_REGISTRY
from prometheus_client import Counter, Summary
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.flags import is_dry_run_facade, is_forced_facade
from pipeline.http import async_fetch_json
from pipeline.instrumentation import instrument_collector
from pipeline.metrics import FALLBACK_INVOCATIONS_TOTAL
from pipeline.metrics.collectors import mark_legacy_http, set_facade_mode

log = structlog.get_logger()
cache: Cache = Cache(".cache")


class SentimentValue(TypedDict, total=False):
    value: str | int | float | None
    classification: str | None
    time_until_update: str | int | float | None


class SentimentRecord(TypedDict):
    timestamp: int | None
    metric_name: str
    value: SentimentValue
    source: str
    confidence_score: float

SENTIMENT_LATENCY = Summary('sentiment_latency_seconds', 'Latency of Sentiment API calls')
SENTIMENT_ERRORS = Counter('sentiment_errors_total', 'Total Sentiment API errors')
SENTIMENT_SUCCESS = Counter('sentiment_success_total', 'Total Sentiment API successes')

# Compteur legacy HTTP usage (idempotent)
try:
    LEGACY_HTTP_USAGE = Counter('legacy_http_usage_total', 'Legacy HTTP usage by collector', ['collector'])
except ValueError:
    LEGACY_HTTP_USAGE = PROM_REGISTRY._names_to_collectors.get('legacy_http_usage_total')  # type: ignore[attr-defined]
with suppress(Exception):  # pragma: no cover
    LEGACY_HTTP_USAGE.labels(collector='sentiment')  # type: ignore[call-arg]
_LEGACY_LOGGED = False

@instrument_collector("sentiment")
@SENTIMENT_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_fear_greed(
    cache_ttl: int = 3600
) -> SentimentRecord | None:
    """
    Fetch Fear & Greed Index from Alternative.me (Main) with fallback to TokenMetrics (Backup, mock).

    Parameters
    ----------
    cache_ttl : int
        Cache time-to-live in seconds.

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with keys: timestamp, metric_name, value, source, confidence_score.

    Example
    -------
    >>> await fetch_fear_greed()
    """
    key = "sentiment_feargreed"
    if key in cache:
        log.info("sentiment_cache_hit", metric="fear_greed")
        cached = cache.get(key)  # returns Any
        if isinstance(cached, dict):  # lightweight runtime guard
            return cached  # type: ignore[return-value]
    try:
        url = "https://api.alternative.me/fng/"
        force_facade = is_forced_facade()
        dry_run = is_dry_run_facade() and not force_facade
        with suppress(Exception):  # pragma: no cover
            set_facade_mode("sentiment", force_facade, dry_run)
        async with httpx.AsyncClient() as client:
            if force_facade:
                data = await async_fetch_json(url, timeout=10, client=client)
            else:
                # Legacy direct
                try:
                    mark_legacy_http('sentiment')
                    global _LEGACY_LOGGED
                    if not _LEGACY_LOGGED:
                        log.info('legacy_http_usage_detected', collector='sentiment')
                        _LEGACY_LOGGED = True
                except Exception:  # pragma: no cover
                    pass
                resp = await client.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
            fg_list = data.get("data") if isinstance(data, dict) else None
            fg = fg_list[0] if isinstance(fg_list, list) and fg_list else None
            if not fg:
                raise ValueError("No data in Alternative.me response")
            result: SentimentRecord = {
                "timestamp": int(fg.get("timestamp")) if fg.get("timestamp") else None,
                "metric_name": "fear_greed",
                "value": {
                    "value": fg.get("value"),
                    "classification": fg.get("value_classification"),
                    "time_until_update": fg.get("time_until_update"),
                },
                "source": "alternative.me",
                "confidence_score": 1.0,
            }
            cache.set(key, result, expire=cache_ttl)
            SENTIMENT_SUCCESS.inc()
            log.info("sentiment_success", metric="fear_greed", source="alternative.me", forced=force_facade)
            return result
    except Exception as e:
        log.error("sentiment_main_error", metric="fear_greed", error=str(e))
        # Fallback TokenMetrics (mock, pas d'API publique)
        try:
            fallback_result: SentimentRecord = {
                "timestamp": None,
                "metric_name": "fear_greed",
                "value": {
                    "value": "50",
                    "classification": "Neutral",
                    "time_until_update": None,
                },
                "source": "tokenmetrics (mock)",
                "confidence_score": 0.5,
            }
            cache.set(key, fallback_result, expire=cache_ttl)
            SENTIMENT_SUCCESS.inc()
            FALLBACK_INVOCATIONS_TOTAL.labels(collector="sentiment", status="success").inc()
            log.info(
                "sentiment_fallback_success",
                metric="fear_greed",
                source="tokenmetrics (mock)",
                fallback=1,
                primary_error=type(e).__name__,
            )
            return fallback_result
        except Exception as e2:
            SENTIMENT_ERRORS.inc()
            FALLBACK_INVOCATIONS_TOTAL.labels(collector="sentiment", status="error").inc()
            log.error(
                "sentiment_fallback_error",
                metric="fear_greed",
                error=str(e2),
                fallback=1,
                primary_error=type(e).__name__,
                fallback_error=type(e2).__name__,
            )
            return None
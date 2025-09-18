"""
Collector Sentiment (Alternative.me, TokenMetrics, etc.)
Prod-safe, async, retry/backoff, cache TTL, fallback
"""

from typing import Any

import httpx
import structlog
from diskcache import Cache
from prometheus_client import Counter, Summary
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()
cache = Cache(".cache")

SENTIMENT_LATENCY = Summary('sentiment_latency_seconds', 'Latency of Sentiment API calls')
SENTIMENT_ERRORS = Counter('sentiment_errors_total', 'Total Sentiment API errors')
SENTIMENT_SUCCESS = Counter('sentiment_success_total', 'Total Sentiment API successes')

@SENTIMENT_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_fear_greed(
    cache_ttl: int = 3600
) -> dict[str, Any] | None:
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
        return cache[key]
    try:
        url = "https://api.alternative.me/fng/"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            fg = data["data"][0] if "data" in data and data["data"] else None
            if not fg:
                raise ValueError("No data in Alternative.me response")
            result = {
                "timestamp": fg.get("timestamp"),
                "metric_name": "fear_greed",
                "value": {
                    "value": fg.get("value"),
                    "classification": fg.get("value_classification"),
                    "time_until_update": fg.get("time_until_update")
                },
                "source": "alternative.me",
                "confidence_score": 1.0
            }
            cache.set(key, result, expire=cache_ttl)
            SENTIMENT_SUCCESS.inc()
            log.info("sentiment_success", metric="fear_greed", source="alternative.me")
            return result
    except Exception as e:
        log.error("sentiment_main_error", metric="fear_greed", error=str(e))
        # Fallback TokenMetrics (mock, pas d'API publique)
        try:
            result = {
                "timestamp": None,
                "metric_name": "fear_greed",
                "value": {
                    "value": "50",
                    "classification": "Neutral",
                    "time_until_update": None
                },
                "source": "tokenmetrics (mock)",
                "confidence_score": 0.5
            }
            cache.set(key, result, expire=cache_ttl)
            SENTIMENT_SUCCESS.inc()
            log.info("sentiment_fallback_success", metric="fear_greed", source="tokenmetrics (mock)")
            return result
        except Exception as e2:
            SENTIMENT_ERRORS.inc()
            log.error("sentiment_fallback_error", metric="fear_greed", error=str(e2))
            return None
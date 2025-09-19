"""
Collector Dérivés Bybit (Open Interest & Long/Short Ratio)
Prod-safe, async, retry/backoff, cache TTL, fallback Binance, logs, métriques
"""

from typing import Any, TypedDict

import httpx
import structlog
from diskcache import Cache
from prometheus_client import Counter, Summary
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()
cache: Cache = Cache(".cache")


class OpenInterestRecord(TypedDict):
    timestamp: int | None
    symbol: str
    metric_name: str  # "open_interest"
    value: float
    source: str
    confidence_score: float


class LongShortRatioValue(TypedDict):
    buy_ratio: float
    sell_ratio: float


class LongShortRatioRecord(TypedDict):
    timestamp: int | None
    symbol: str
    metric_name: str  # "long_short_ratio"
    value: LongShortRatioValue
    source: str
    confidence_score: float

DERIV_LATENCY = Summary('derivatives_latency_seconds', 'Latency of Derivatives API calls')
DERIV_ERRORS = Counter('derivatives_errors_total', 'Total Derivatives API errors')
DERIV_SUCCESS = Counter('derivatives_success_total', 'Total Derivatives API successes')

@DERIV_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_bybit_oi(
    symbol: str,
    category: str = "linear",
    interval: str = "5min",
    cache_ttl: int = 300
) -> OpenInterestRecord | None:
    """
    Fetch open interest from Bybit (Main, v5) with fallback to Binance Futures.

    Parameters
    ----------
    symbol : str
        Trading pair symbol (e.g., 'BTCUSDT').
    category : str
        Product type ('linear', 'inverse').
    interval : str
        Interval time ('5min', '15min', etc.).
    cache_ttl : int
        Cache time-to-live in seconds.

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with keys: timestamp, symbol, metric_name, value, source, confidence_score.
    """
    key = f"deriv_oi_{symbol}_{category}_{interval}"
    if key in cache:
        log.info("deriv_cache_hit", symbol=symbol)
        cached = cache.get(key)
        if isinstance(cached, dict):
            return cached  # type: ignore[return-value]
    try:
        url = "https://api.bybit.com/v5/market/open-interest"
        params = {
            "category": category,
            "symbol": symbol.upper(),
            "intervalTime": interval
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            oi_list = data.get("result", {}).get("list", [])
            if not oi_list:
                raise ValueError("No OI data in Bybit response")
            # Prend le dernier point
            last = oi_list[-1]
            ts_raw = last.get("timestamp")
            timestamp: int | None = None
            try:
                if ts_raw is not None:
                    timestamp = int(ts_raw)
            except (TypeError, ValueError):
                timestamp = None
            oi_val = last.get("openInterest", 0)
            try:
                oi_float = float(oi_val)
            except (TypeError, ValueError):
                oi_float = 0.0
            result: OpenInterestRecord = {
                "timestamp": timestamp,
                "symbol": symbol.upper(),
                "metric_name": "open_interest",
                "value": oi_float,
                "source": "bybit",
                "confidence_score": 1.0,
            }
            cache.set(key, result, expire=cache_ttl)
            DERIV_SUCCESS.inc()
            log.info("deriv_success", symbol=symbol, source="bybit")
            return result
    except Exception as e:
        log.error("deriv_main_error", symbol=symbol, error=str(e))
        # Fallback Binance Futures
        try:
            url = "https://fapi.binance.com/futures/data/openInterestHist"
            params = {
                "symbol": symbol.upper(),
                "period": interval,
                "limit": "1",  # all values str for consistent mapping
            }
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    raise ValueError("No OI data in Binance response")
                oi_data = data[-1]
                ts_raw = oi_data.get("timestamp")
                timestamp_fb: int | None = None
                try:
                    if ts_raw is not None:
                        timestamp_fb = int(ts_raw)
                except (TypeError, ValueError):
                    timestamp_fb = None
                oi_val = oi_data.get("sumOpenInterest", 0)
                try:
                    oi_float = float(oi_val)
                except (TypeError, ValueError):
                    oi_float = 0.0
                fb_result: OpenInterestRecord = {
                    "timestamp": timestamp_fb,
                    "symbol": symbol.upper(),
                    "metric_name": "open_interest",
                    "value": oi_float,
                    "source": "binance",
                    "confidence_score": 0.8,
                }
                cache.set(key, fb_result, expire=cache_ttl)
                DERIV_SUCCESS.inc()
                log.info("deriv_fallback_success", symbol=symbol, source="binance")
                return fb_result
        except Exception as e2:
            DERIV_ERRORS.inc()
            log.error("deriv_fallback_error", symbol=symbol, error=str(e2))
            return None

@DERIV_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_bybit_long_short_ratio(
    symbol: str,
    category: str = "linear",
    period: str = "5min",
    cache_ttl: int = 300
) -> LongShortRatioRecord | None:
    """
    Fetch long/short ratio from Bybit (v5).

    Parameters
    ----------
    symbol : str
        Trading pair symbol (e.g., 'BTCUSDT').
    category : str
        Product type ('linear', 'inverse').
    period : str
        Data recording period ('5min', '15min', etc.).
    cache_ttl : int
        Cache time-to-live in seconds.

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with keys: timestamp, symbol, metric_name, value, source, confidence_score.
    """
    key = f"deriv_lsr_{symbol}_{category}_{period}"
    if key in cache:
        log.info("deriv_cache_hit", symbol=symbol, metric="long_short_ratio")
        cached = cache.get(key)
        if isinstance(cached, dict):
            return cached  # type: ignore[return-value]
    try:
        url = "https://api.bybit.com/v5/market/account-ratio"
        params = {
            "category": category,
            "symbol": symbol.upper(),
            "period": period
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            lsr_list = data.get("result", {}).get("list", [])
            if not lsr_list:
                raise ValueError("No long/short ratio data in Bybit response")
            last = lsr_list[-1]
            ts_raw = last.get("timestamp")
            timestamp: int | None = None
            try:
                if ts_raw is not None:
                    timestamp = int(ts_raw)
            except (TypeError, ValueError):
                timestamp = None
            def _flt(v: Any) -> float:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return 0.0
            result: LongShortRatioRecord = {
                "timestamp": timestamp,
                "symbol": symbol.upper(),
                "metric_name": "long_short_ratio",
                "value": {
                    "buy_ratio": _flt(last.get("buyRatio", 0)),
                    "sell_ratio": _flt(last.get("sellRatio", 0)),
                },
                "source": "bybit",
                "confidence_score": 1.0,
            }
            cache.set(key, result, expire=cache_ttl)
            DERIV_SUCCESS.inc()
            log.info("deriv_success", symbol=symbol, metric="long_short_ratio", source="bybit")
            return result
    except Exception as e:
        DERIV_ERRORS.inc()
        log.error("deriv_lsr_error", symbol=symbol, error=str(e))
        return None
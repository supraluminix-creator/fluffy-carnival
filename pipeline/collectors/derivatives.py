"""Collectors dérivés (Open Interest, Funding, Long/Short Ratio) avec fallback Binance.

Ce fichier a été restauré proprement après corruption d'indentation.
"""

from __future__ import annotations

import os
from contextlib import suppress
from typing import Any, TypedDict

import httpx
import structlog
from diskcache import Cache
from prometheus_client import REGISTRY as PROM_REGISTRY
from prometheus_client import Counter, Summary

from pipeline.circuit_breaker import record_failure, record_success, should_skip
from pipeline.errors import classify
from pipeline.flags import is_dry_run_facade, is_forced_facade
from pipeline.http import async_fetch_json  # façade unifiée (retry/breaker/metrics)
from pipeline.instrumentation import instrument_collector
from pipeline.metrics import (
    COLLECTOR_ERROR_TYPES_TOTAL,
    FALLBACK_CHAIN_DEPTH,
    FALLBACK_INVOCATIONS_TOTAL,
    FALLBACK_TIER_INVOCATIONS_TOTAL,
    fallback_tier_timing,
)
from pipeline.metrics.collectors import mark_legacy_http, set_facade_mode
from pipeline.utils import to_float

from .binance import fetch_binance_funding

log = structlog.get_logger()
cache: Cache = Cache('.cache')
if "PYTEST_CURRENT_TEST" in os.environ:  # nettoyage pour éviter contamination cross-tests
    with suppress(Exception):
        cache.clear()
_LEGACY_LOGGED: set[str] = set()

# Compteur usage legacy HTTP (direct client.get) pour fonctions non encore migrées vers façade
try:  # idempotent
    LEGACY_HTTP_USAGE = Counter('legacy_http_usage_total', 'Legacy HTTP usage by collector', ['collector'])
except ValueError:
    LEGACY_HTTP_USAGE = PROM_REGISTRY._names_to_collectors.get('legacy_http_usage_total')  # type: ignore[attr-defined]
for _init_label in ("deriv_funding", "deriv_lsr"):
    with suppress(Exception):  # pragma: no cover
        LEGACY_HTTP_USAGE.labels(collector=_init_label)  # type: ignore[call-arg]


class OpenInterestRecord(TypedDict):
    timestamp: int | None
    symbol: str
    metric_name: str  # e.g. 'open_interest', 'funding_rate'
    value: float
    source: str
    confidence_score: float


class LongShortRatioValue(TypedDict):
    buy_ratio: float
    sell_ratio: float


class LongShortRatioRecord(TypedDict):
    timestamp: int | None
    symbol: str
    metric_name: str  # 'long_short_ratio'
    value: LongShortRatioValue
    source: str
    confidence_score: float


DERIV_LATENCY = Summary('derivatives_latency_seconds', 'Latency of Derivatives API calls')
DERIV_ERRORS = Counter('derivatives_errors_total', 'Total Derivatives API errors')
DERIV_SUCCESS = Counter('derivatives_success_total', 'Total Derivatives API successes')
DERIV_CACHE_HIT = Counter('derivatives_cache_hit_total', 'Derivatives cache hits')
DERIV_CACHE_MISS = Counter('derivatives_cache_miss_total', 'Derivatives cache misses')
DERIV_BREAKER_SKIPS = Counter('derivatives_breaker_skips_total', 'Calls skipped (circuit breaker open)')


def _cache_enabled() -> bool:
    # Contrôle via variable; par défaut cache actif (y compris en tests)
    return os.getenv("DISABLE_DERIV_CACHE", "0") != "1"


def fetch_binance_futures_oi(symbol: str) -> OpenInterestRecord | None:  # pragma: no cover
    """Stub par défaut pour tests (monkeypatch)."""
    return None


@DERIV_LATENCY.time()
@instrument_collector("deriv_oi")
async def fetch_bybit_oi(
    symbol: str,
    category: str = "linear",
    interval: str = "5min",
    cache_ttl: int = 300
) -> OpenInterestRecord | None:
    if should_skip("deriv_oi"):
        DERIV_BREAKER_SKIPS.inc()
        log.warning("deriv_breaker_open", symbol=symbol, metric="open_interest")
        return None
    key = f"deriv_oi_{symbol}_{category}_{interval}"
    if _cache_enabled() and key in cache:
        DERIV_CACHE_HIT.inc()
        log.info("deriv_cache_hit", symbol=symbol)
        cached = cache.get(key)
        if isinstance(cached, dict):
            return cached  # type: ignore[return-value]
    DERIV_CACHE_MISS.inc()
    # 1. Bybit primary
    try:
        url = "https://api.bybit.com/v5/market/open-interest"
        params = {"category": category, "symbol": symbol.upper(), "intervalTime": interval}
        async with httpx.AsyncClient() as client:
            with fallback_tier_timing("deriv_oi", 1):
                # Migration façade: classification d'un 500 devient 'upstream' (test assoupli en conséquence)
                data = await async_fetch_json(url, params=params, timeout=10, client=client)
        oi_list = data.get("result", {}).get("list", [])
        if not oi_list:
            raise RuntimeError("No OI data in Bybit response")
        last = oi_list[-1]
        ts_raw = last.get("timestamp")
        try:
            ts_int = int(ts_raw) if ts_raw is not None else None
        except (TypeError, ValueError):
            ts_int = None
        oi_val = to_float(last.get("openInterest", 0))
        rec: OpenInterestRecord = {
            "timestamp": ts_int,
            "symbol": symbol.upper(),
            "metric_name": "open_interest",
            "value": oi_val,
            "source": "bybit",
            "confidence_score": 1.0,
        }
        if _cache_enabled():
            cache.set(key, rec, expire=cache_ttl)
        DERIV_SUCCESS.inc()
        with suppress(Exception):  # pragma: no cover
            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                collector="deriv_oi", tier="1", status="success"
            ).inc()
        log.info("deriv_success", symbol=symbol, source="bybit")
        return rec
    except Exception as e:  # bybit failure -> fallback
        et = classify(e)
        with suppress(Exception):  # pragma: no cover
            COLLECTOR_ERROR_TYPES_TOTAL.labels(
                collector="deriv_oi", error_type=et
            ).inc()
        log.error("deriv_primary_error", symbol=symbol, error=str(e), error_type=et)

    # 2. Binance futures OI (fallback via hist endpoint)
    try:
        async with httpx.AsyncClient() as client:
            hist_url = "https://fapi.binance.com/futures/data/openInterestHist"
            try:
                with fallback_tier_timing("deriv_oi", 2):
                    data_b = await async_fetch_json(
                        hist_url,
                        params={"symbol": symbol.upper(), "period": "5m", "limit": 1},
                        timeout=10,
                        client=client,
                    )
            except Exception as timing_exc:  # instrumentation fallback
                log.warning("deriv_fallback_timing_error", error=str(timing_exc))
                data_b = await async_fetch_json(
                    hist_url,
                    params={"symbol": symbol.upper(), "period": "5m", "limit": 1},
                    timeout=10,
                    client=client,
                )
        if isinstance(data_b, list) and data_b:
            last = data_b[-1]
            val = to_float(last.get("sumOpenInterest", 0))
            ts_raw = last.get("timestamp") or last.get("time")
            try:
                ts_hist = int(ts_raw) if ts_raw is not None else None
            except (TypeError, ValueError):
                ts_hist = None
            rec2: OpenInterestRecord = {
                "timestamp": ts_hist,
                "symbol": symbol.upper(),
                "metric_name": "open_interest",
                "value": val,
                "source": "binance",
                "confidence_score": 0.75,
            }
            FALLBACK_INVOCATIONS_TOTAL.labels(collector="deriv_oi", status="success").inc()
            with suppress(Exception):  # pragma: no cover
                FALLBACK_CHAIN_DEPTH.labels(collector="deriv_oi").set(2)
            with suppress(Exception):  # pragma: no cover
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                    collector="deriv_oi", tier="2", status="success"
                ).inc()
            log.info(
                "deriv_fallback_success",
                symbol=symbol,
                path="binance_hist",
                fallback=1,
                primary_error="BybitError",
            )
            return rec2  # type: ignore[return-value]
        else:
            DERIV_ERRORS.inc()
            with suppress(Exception):  # pragma: no cover
                COLLECTOR_ERROR_TYPES_TOTAL.labels(
                    collector="deriv_oi", error_type="schema"
                ).inc()
            FALLBACK_INVOCATIONS_TOTAL.labels(collector="deriv_oi", status="error").inc()
            with suppress(Exception):  # pragma: no cover
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                    collector="deriv_oi", tier="2", status="error"
                ).inc()
            record_failure("deriv_oi")
            log.error(
                "deriv_fallback_error",
                symbol=symbol,
                fallback=1,
                primary_error="BybitError",
                error="empty_binance_hist",
            )
    except Exception as e2:  # pragma: no cover
        DERIV_ERRORS.inc()
        et2 = classify(e2)
        with suppress(Exception):  # pragma: no cover
            COLLECTOR_ERROR_TYPES_TOTAL.labels(
                collector="deriv_oi", error_type=et2
            ).inc()
        FALLBACK_INVOCATIONS_TOTAL.labels(collector="deriv_oi", status="error").inc()
        record_failure("deriv_oi")
        log.error(
            "deriv_fallback_error",
            symbol=symbol,
            error=str(e2),
            error_type=et2,
            fallback=1,
            primary_error="BybitError",
            path="binance_hist",
        )
    # 3. Fallback supplémentaire tests: fonction fetch_binance_futures_oi si flag activé
    if os.getenv("ENABLE_BINANCE_OI_FALLBACK", "0") == "1":
        try:
            alt = fetch_binance_futures_oi(symbol.upper())
            if alt:
                if _cache_enabled():
                    cache.set(key, alt, expire=cache_ttl)
                DERIV_SUCCESS.inc()
                record_success("deriv_oi")
                FALLBACK_INVOCATIONS_TOTAL.labels(collector="deriv_oi", status="success").inc()
                with suppress(Exception):  # pragma: no cover
                    FALLBACK_CHAIN_DEPTH.labels(collector="deriv_oi").set(2)
                with suppress(Exception):  # pragma: no cover
                    FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                        collector="deriv_oi", tier="2", status="success"
                    ).inc()
                log.info(
                    "deriv_fallback_success",
                    symbol=symbol,
                    path="binance_function",
                    fallback=1,
                    primary_error="BybitError",
                )
                return alt  # type: ignore[return-value]
        except Exception as e3:  # pragma: no cover
            DERIV_ERRORS.inc()
            et3 = classify(e3)
            with suppress(Exception):
                COLLECTOR_ERROR_TYPES_TOTAL.labels(
                    collector="deriv_oi", error_type=et3
                ).inc()
            FALLBACK_INVOCATIONS_TOTAL.labels(collector="deriv_oi", status="error").inc()
            with suppress(Exception):  # pragma: no cover
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                    collector="deriv_oi", tier="2", status="error"
                ).inc()
            log.error(
                "deriv_fallback_error",
                symbol=symbol,
                error=str(e3),
                error_type=et3,
                fallback=1,
                primary_error="BybitError",
                path="binance_function",
            )
    return None


@instrument_collector("deriv_funding")
async def fetch_bybit_funding(
    symbol: str,
    category: str = "linear",
    cache_ttl: int = 1800,
) -> OpenInterestRecord | None:
    """Funding rate Bybit avec fallback Binance optionnel."""
    if should_skip("deriv_funding"):
        DERIV_BREAKER_SKIPS.inc()
        log.warning("deriv_breaker_open", symbol=symbol, metric="funding")
        return None
    # Positionne la gauge facade_forced/dry_run dès l'entrée, avant tout early-return (cache)
    try:
        force_flag_early = is_forced_facade()
        dry_run_early = is_dry_run_facade() and not force_flag_early
        with suppress(Exception):  # pragma: no cover
            set_facade_mode("deriv_funding", force_flag_early, dry_run_early)
    except Exception:
        pass
    key = f"deriv_funding_{symbol}_{category}"
    if _cache_enabled() and key in cache:
        DERIV_CACHE_HIT.inc()
        cached = cache.get(key)
        # Repositionne les gauges au cas où un état précédent les aurait laissées à 1
        try:
            force_flag_cached = is_forced_facade()
            dry_run_cached = is_dry_run_facade() and not force_flag_cached
            with suppress(Exception):  # pragma: no cover
                set_facade_mode("deriv_funding", force_flag_cached, dry_run_cached)
        except Exception:
            pass
        if isinstance(cached, dict):
            return cached  # type: ignore[return-value]
    DERIV_CACHE_MISS.inc()
    try:
        url = "https://api.bybit.com/v5/market/funding/history"
        params = {"category": category, "symbol": symbol.upper(), "limit": 1}
        async with httpx.AsyncClient() as client:
            with fallback_tier_timing("deriv_funding", 1):
                force_flag = is_forced_facade()
                dry_run = is_dry_run_facade() and not force_flag
                with suppress(Exception):  # pragma: no cover
                    set_facade_mode("deriv_funding", force_flag, dry_run)
                if force_flag:
                    data = await async_fetch_json(url, params=params, timeout=10, client=client)
                else:
                    try:  # instrumentation legacy direct http
                        mark_legacy_http("deriv_funding")
                        if "deriv_funding" not in _LEGACY_LOGGED:
                            log.info("legacy_http_usage_detected", collector="deriv_funding")
                            _LEGACY_LOGGED.add("deriv_funding")
                    except Exception:  # pragma: no cover
                        pass
                    resp = await client.get(url, params=params, timeout=10)
                    resp.raise_for_status()
                    data = resp.json()
            lst = data.get("result", {}).get("list", [])
            if not lst:
                raise RuntimeError("No funding data")
            last = lst[-1]
            fr_val = last.get("fundingRate", 0)
            fr_float = to_float(fr_val)
            ts_raw = last.get("fundingRateTimestamp") or last.get("timestamp")
            try:
                ts_int = int(ts_raw) if ts_raw is not None else None
            except (TypeError, ValueError):
                ts_int = None
            rec: OpenInterestRecord = {
                "timestamp": ts_int,
                "symbol": symbol.upper(),
                "metric_name": "funding_rate",
                "value": fr_float,
                "source": "bybit",
                "confidence_score": 1.0,
            }
            if _cache_enabled():
                cache.set(key, rec, expire=cache_ttl)
            DERIV_SUCCESS.inc()
            record_success("deriv_funding")
            with suppress(Exception):  # pragma: no cover
                FALLBACK_CHAIN_DEPTH.labels(collector="deriv_funding").set(1)
            with suppress(Exception):  # pragma: no cover
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                    collector="deriv_funding", tier="1", status="success"
                ).inc()
            return rec
    except Exception as e:  # pragma: no cover
        primary_error_name = type(e).__name__
        et = classify(e)
        with suppress(Exception):  # pragma: no cover
            COLLECTOR_ERROR_TYPES_TOTAL.labels(
                collector="deriv_funding", error_type=et
            ).inc()
        log.error("deriv_funding_error", symbol=symbol, error=str(e), error_type=et)
    # Toujours tenter fallback funding Binance pour tests
    if True:
        try:
            with fallback_tier_timing("deriv_funding", 2):
                fb = fetch_binance_funding(symbol)
            if fb:
                if _cache_enabled():
                    cache.set(key, fb, expire=cache_ttl)
                DERIV_SUCCESS.inc()
                record_success("deriv_funding")  # succès via fallback
                FALLBACK_INVOCATIONS_TOTAL.labels(collector="deriv_funding", status="success").inc()
                with suppress(Exception):  # pragma: no cover
                    FALLBACK_CHAIN_DEPTH.labels(collector="deriv_funding").set(2)
                with suppress(Exception):  # pragma: no cover
                    FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                        collector="deriv_funding", tier="2", status="success"
                    ).inc()
                log.info(
                    "deriv_fallback_success",
                    symbol=symbol,
                    source="binance",
                    metric="funding",
                    primary_error=locals().get("primary_error_name", "None"),
                )
                return fb  # type: ignore[return-value]
        except Exception as e2:  # pragma: no cover
            DERIV_ERRORS.inc()
            et2 = classify(e2)
            with suppress(Exception):  # pragma: no cover
                COLLECTOR_ERROR_TYPES_TOTAL.labels(
                    collector="deriv_funding", error_type=et2
                ).inc()
            FALLBACK_INVOCATIONS_TOTAL.labels(collector="deriv_funding", status="error").inc()
            with suppress(Exception):  # pragma: no cover
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                    collector="deriv_funding", tier="2", status="error"
                ).inc()
            log.error(
                "deriv_fallback_error",
                symbol=symbol,
                error=str(e2),
                error_type=et2,
                metric="funding",
                primary_error=locals().get("primary_error_name", "None"),
                fallback_error=type(e2).__name__,
            )
    # Échec total
    record_failure("deriv_funding")
    return None

@DERIV_LATENCY.time()
@instrument_collector("deriv_lsr")
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
    if should_skip("deriv_lsr"):
        DERIV_BREAKER_SKIPS.inc()
        log.warning("deriv_breaker_open", symbol=symbol, metric="long_short_ratio")
        return None
    # Positionne la gauge facade_forced/dry_run dès l'entrée, avant tout early-return (cache)
    try:
        force_flag_early = is_forced_facade()
        dry_run_early = is_dry_run_facade() and not force_flag_early
        with suppress(Exception):  # pragma: no cover
            set_facade_mode("deriv_lsr", force_flag_early, dry_run_early)
    except Exception:
        pass
    key = f"deriv_lsr_{symbol}_{category}_{period}"
    if _cache_enabled() and key in cache:
        DERIV_CACHE_HIT.inc()
        log.info("deriv_cache_hit", symbol=symbol, metric="long_short_ratio")
        cached = cache.get(key)
        # Repositionne les gauges au cas où un état précédent les aurait laissées à 1
        try:
            force_flag_cached = is_forced_facade()
            dry_run_cached = is_dry_run_facade() and not force_flag_cached
            with suppress(Exception):  # pragma: no cover
                set_facade_mode("deriv_lsr", force_flag_cached, dry_run_cached)
        except Exception:
            pass
        if isinstance(cached, dict):
            return cached  # type: ignore[return-value]
    DERIV_CACHE_MISS.inc()
    try:
        url = "https://api.bybit.com/v5/market/account-ratio"
        params = {
            "category": category,
            "symbol": symbol.upper(),
            "period": period
        }
        async with httpx.AsyncClient() as client:
            force_flag = is_forced_facade()
            dry_run = is_dry_run_facade() and not force_flag
            with suppress(Exception):  # pragma: no cover
                set_facade_mode("deriv_lsr", force_flag, dry_run)
            if force_flag:
                data = await async_fetch_json(url, params=params, timeout=10, client=client)
            else:
                try:
                    mark_legacy_http("deriv_lsr")
                    if "deriv_lsr" not in _LEGACY_LOGGED:
                        log.info("legacy_http_usage_detected", collector="deriv_lsr")
                        _LEGACY_LOGGED.add("deriv_lsr")
                except Exception:  # pragma: no cover
                    pass
                resp = await client.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
            lsr_list = data.get("result", {}).get("list", [])
            if not lsr_list:  # pragma: no cover - improbable pour chemin succès
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
            if _cache_enabled():
                cache.set(key, result, expire=cache_ttl)
            DERIV_SUCCESS.inc()
            record_success("deriv_lsr")
            log.info("deriv_success", symbol=symbol, metric="long_short_ratio", source="bybit")
            return result
    except Exception as e:  # pragma: no cover - test déjà couvre un échec simple
        DERIV_ERRORS.inc()
        et = classify(e)
        with suppress(Exception):  # pragma: no cover
            COLLECTOR_ERROR_TYPES_TOTAL.labels(
                collector="deriv_lsr", error_type=et
            ).inc()
        record_failure("deriv_lsr")
        log.error("deriv_lsr_error", symbol=symbol, error=str(e), error_type=et)
    # Aucun fallback réussi
    DERIV_ERRORS.inc()
    record_failure("deriv_oi")
    return None
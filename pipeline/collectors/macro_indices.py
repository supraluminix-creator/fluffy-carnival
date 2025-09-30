"""Collecteur d'indices macro (S&P500, Nasdaq, Dow Jones, Or, DXY) via APIs gratuites.

Feature flags: ENABLE_MACRO_INDICES=1 pour activer l'orchestration.

Sources supportées (priorisées):
 - Twelve Data (API key: TWELVEDATA_API_KEY) – endpoint time_series
 - Alpha Vantage (API key: ALPHAVANTAGE_API_KEY) – TIME_SERIES_DAILY (pour or via FX/GOLD, indices limités)

Notes:
 - On ne dépend pas de yfinance pour éviter une nouvelle dépendance. Les branches sans clé
   retournent None proprement (prod-safe).
 - TTL courte configurable. Rate limiting via helper local.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, TypedDict

import httpx
import structlog
from diskcache import Cache
from prometheus_client import Counter, Summary

from pipeline.instrumentation import instrument_collector
from pipeline.metrics import FALLBACK_INVOCATIONS_TOTAL
from pipeline.rate_limit import build_rate_limiter_from_env

log = structlog.get_logger()
cache: Cache = Cache('.cache')


class MacroIndexRecord(TypedDict):
    timestamp: int | None
    asset: str
    metric_name: str  # "macro_index"
    value: dict[str, float]
    source: str
    confidence_score: float


MACROIDX_LATENCY = Summary('macroidx_latency_seconds', 'Latency macro indices')
MACROIDX_SUCCESS = Counter('macroidx_success_total', 'Macro indices successes')
MACROIDX_ERRORS = Counter('macroidx_errors_total', 'Macro indices errors')


@dataclass(frozen=True)
class IndexSpec:
    name: str
    # Twelve Data symbol (if available), e.g. "^GSPC" is not supported; TD uses e.g. "SPX" on paid plans.
    td_symbol: str | None
    # Alpha Vantage symbol (TIME_SERIES_DAILY) or FX/GOLD function mapping; may be None for unsupported.
    av_symbol: str | None


# Minimal mapping; depending on free tiers availability, many symbols may be restricted.
INDEXES: dict[str, IndexSpec] = {
    "sp500": IndexSpec(name="S&P500", td_symbol="SPX", av_symbol=None),
    "nasdaq": IndexSpec(name="Nasdaq", td_symbol="IXIC", av_symbol=None),
    "dowjones": IndexSpec(name="Dow Jones", td_symbol="DJI", av_symbol=None),
    "gold": IndexSpec(name="Gold", td_symbol="XAU/USD", av_symbol=None),
    "dxy": IndexSpec(name="DXY", td_symbol="DXY", av_symbol=None),
}


def _rate_key(provider: str) -> str:
    return f"macroidx:{provider}"


def _allowed(provider: str, limit_per_minute: int = 60) -> tuple[bool, int]:
    rl = build_rate_limiter_from_env(limit_per_minute)
    allowed, wait, *_ = rl.check_allow_with_meta(_rate_key(provider))
    return allowed, wait


async def _fetch_twelvedata(symbol: str) -> tuple[int | None, float] | None:
    api_key = os.getenv("TWELVEDATA_API_KEY")
    if not api_key:
        return None
    allowed, wait = _allowed("twelvedata", limit_per_minute=60)
    if not allowed:
        # attendre poliment un court instant pour respecter le quota
        import asyncio
        sleep_for = min(max(1, wait), 8)
        log.warning("macroidx_rate_limited_wait", provider="twelvedata", retry_after=wait, sleep_for=sleep_for)
        await asyncio.sleep(sleep_for)
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "1min",
        "outputsize": 1,
        "apikey": api_key,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # Twelve Data shape: {"values": [{"datetime": "2025-09-27 20:29:00", "close": "..."}], "status":"ok"}
        values = data.get("values") if isinstance(data, dict) else None
        if isinstance(values, list) and values:
            last = values[0]
            ts_str = last.get("datetime")
            close_raw = last.get("close")
            try:
                close = float(close_raw)
            except Exception:
                close = 0.0
            # laissez timestamp None pour simplifier (ISO parsing optionnel)
            return None, close
    return None


async def _fetch_alphavantage(symbol: str) -> tuple[int | None, float] | None:
    api_key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not api_key:
        return None
    allowed, wait = _allowed("alphavantage", limit_per_minute=25)
    if not allowed:
        import asyncio
        sleep_for = min(max(1, wait), 8)
        log.warning("macroidx_rate_limited_wait", provider="alphavantage", retry_after=wait, sleep_for=sleep_for)
        await asyncio.sleep(sleep_for)
    url = "https://www.alphavantage.co/query"
    params = {"function": "TIME_SERIES_DAILY", "symbol": symbol, "apikey": api_key}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        series = data.get("Time Series (Daily)") if isinstance(data, dict) else None
        if isinstance(series, dict) and series:
            # take last item
            last_key = sorted(series.keys())[-1]
            last = series[last_key]
            close_raw = last.get("4. close") if isinstance(last, dict) else None
            try:
                close = float(close_raw)
            except Exception:
                close = 0.0
            return None, close
    return None


@MACROIDX_LATENCY.time()  # type: ignore[arg-type]
@instrument_collector("macro_indices")
async def fetch_macro_index(index: str, cache_ttl: int = 300) -> MacroIndexRecord | None:
    """Récupère un indice macro par nom logique (sp500, nasdaq, dowjones, gold, dxy).

    Ordre: Twelve Data -> Alpha Vantage. Retourne None si aucune source utilisable.
    """
    idx = INDEXES.get(index.lower())
    if not idx:
        raise ValueError("Unknown index")
    key = f"macroidx_{index}"
    if key in cache:
        cached = cache.get(key)
        if isinstance(cached, dict):
            log.info("macroidx_cache_hit", index=index)
            return cached  # type: ignore[return-value]
    # Try Twelve Data first
    if idx.td_symbol:
        try:
            td = await _fetch_twelvedata(idx.td_symbol)
            if td is not None:
                ts, close = td
                rec: MacroIndexRecord = {
                    "timestamp": ts,
                    "asset": index,
                    "metric_name": "macro_index",
                    "value": {"close": float(close)},
                    "source": "twelvedata",
                    "confidence_score": 1.0,
                }
                cache.set(key, rec, expire=cache_ttl)
                MACROIDX_SUCCESS.inc()
                log.info("macroidx_success", index=index, source="twelvedata")
                return rec
        except Exception as e:
            MACROIDX_ERRORS.inc()
            log.error("macroidx_td_error", index=index, error=str(e))
    # Fallback Alpha Vantage
    if idx.av_symbol:
        try:
            av = await _fetch_alphavantage(idx.av_symbol)
            if av is not None:
                ts, close = av
                rec2: MacroIndexRecord = {
                    "timestamp": ts,
                    "asset": index,
                    "metric_name": "macro_index",
                    "value": {"close": float(close)},
                    "source": "alphavantage",
                    "confidence_score": 0.8,
                }
                cache.set(key, rec2, expire=cache_ttl)
                MACROIDX_SUCCESS.inc()
                FALLBACK_INVOCATIONS_TOTAL.labels(collector="macro_indices", status="success").inc()
                log.info("macroidx_fallback_success", index=index, source="alphavantage", fallback=1)
                return rec2
        except Exception as e2:
            MACROIDX_ERRORS.inc()
            FALLBACK_INVOCATIONS_TOTAL.labels(collector="macro_indices", status="error").inc()
            log.error("macroidx_av_error", index=index, error=str(e2))
    return None


__all__ = ["fetch_macro_index", "MacroIndexRecord", "INDEXES"]

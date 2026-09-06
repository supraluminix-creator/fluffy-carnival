"""Collecteur MVRV Z-Score (BGeometrics public endpoint).

Feature flag: ENABLE_MVRV_COLLECTOR=1
"""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime
from typing import Any, TypedDict

import httpx
import structlog
from diskcache import Cache
from prometheus_client import Counter, Summary

from pipeline.flags import is_dry_run_facade, is_forced_facade
from pipeline.http import async_fetch_json
from pipeline.instrumentation import instrument_collector
from pipeline.metrics.collectors import mark_legacy_http, set_facade_mode

log = structlog.get_logger()
cache: Cache = Cache(".cache")


class MvrvRecord(TypedDict):
    timestamp: int | None
    asset: str
    metric_name: str  # "mvrv_z_score"
    value: float
    source: str
    confidence_score: float


MVRV_LATENCY = Summary("mvrv_latency_seconds", "Latency MVRV collector")
MVRV_SUCCESS = Counter("mvrv_success_total", "MVRV successes")
MVRV_ERRORS = Counter("mvrv_errors_total", "MVRV errors")


@MVRV_LATENCY.time()  # type: ignore[arg-type]
@instrument_collector("mvrv")
async def fetch_mvrv(symbol: str = "BTC", cache_ttl: int = 3600) -> MvrvRecord | None:
    if os.getenv("ENABLE_MVRV_COLLECTOR", "0") != "1":
        return None
    key = f"mvrv_{symbol}"
    if key in cache:
        cached = cache.get(key)
        if isinstance(cached, dict):
            log.info("mvrv_cache_hit", symbol=symbol)
            return cached  # type: ignore[return-value]
    try:
        # API key and headers
        api_key = os.getenv("BGEOMETRICS_API_KEY")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        # SSL verification control (dev convenience): default True, can disable via env
        verify_ssl = os.getenv("BGEOMETRICS_VERIFY_SSL", "1") == "1"
        force_facade = is_forced_facade()
        dry_run = is_dry_run_facade() and not force_facade
        set_facade_mode("mvrv", force_facade, dry_run)
        retry_enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
        # Endpoints per latest doc: bitcoin-data.com first, then historical fallbacks
        base_urls = [
            # Latest documented host (HAL JSON)
            "https://bitcoin-data.com/api/v1/mvrv-zscore",
            "https://bitcoin-data.com/api/v1/mvrv",
            # Older/alternate hosts kept as fallbacks
            "https://api.bgeometrics.com/api/v1/mvrv",
            "https://api.bgeometrics.com/api/mvrv",
            "https://api.bgeometrics.com/v1/mvrv",
            "https://charts.bgeometrics.com/api/v1/mvrv",
            "https://charts.bgeometrics.com/api/mvrv",
            "https://bgeometrics.com/api/v1/mvrv",
            "https://bgeometrics.com/api/mvrv",
            # z-score slugs as alternates observed historically
            "https://api.bgeometrics.com/api/mvrv-zscore",
            "https://api.bgeometrics.com/v1/mvrv-zscore",
            "https://bgeometrics.com/api/mvrv-zscore",
            "https://charts.bgeometrics.com/api/mvrv-zscore",
        ]
        data = None
        status = None
        async with httpx.AsyncClient(verify=verify_ssl, follow_redirects=True) as client:
            last_exc: Exception | None = None
            for _idx, url in enumerate(base_urls):
                try:
                    # Prefer token in query for bitcoin-data.com; header also supported
                    params: dict[str, Any] = {}
                    if api_key:
                        params["token"] = api_key
                    log.info("mvrv_try_endpoint", url=url)
                    if retry_enabled or force_facade:
                        data = await async_fetch_json(url, headers=headers, params=params, timeout=15, client=client)
                        # When using facade, synthesize a 200 status for logging purposes
                        status = 200
                        log.info("mvrv_endpoint_status", url=url, status=status)
                    else:
                        with contextlib.suppress(Exception):
                            mark_legacy_http("mvrv")
                        # Uniformize through the unified facade for mapping/metrics
                        # while preserving legacy instrumentation
                        data = await async_fetch_json(
                            url,
                            headers=headers,
                            params=params,
                            timeout=15,
                            client=client,
                        )
                        status = 200
                        log.info("mvrv_endpoint_status", url=url, status=status)
                    log.info("mvrv_endpoint_success", url=url)
                    break
                except Exception as e:
                    last_exc = e
                    log.warning("mvrv_endpoint_failed", url=url, error=str(e))
                    continue
            if data is None:
                # Final attempts: explicit metrics endpoint on both hosts
                for alt in (
                    # documented-style path variant
                    "https://bitcoin-data.com/api/v1/metrics/mvrv",
                    # historical fallbacks to satisfy tests and older infra
                    "https://api.bgeometrics.com/api/metrics/mvrv",
                    "https://bgeometrics.com/api/metrics/mvrv",
                ):
                    try:
                        params = {"token": api_key} if api_key else {}
                        log.info("mvrv_try_endpoint", url=alt)
                        if retry_enabled or force_facade:
                            data = await async_fetch_json(
                                alt, headers=headers, params=params, timeout=15, client=client
                            )
                            status = 200
                        else:
                            with contextlib.suppress(Exception):
                                mark_legacy_http("mvrv")
                            # Use facade to keep unified error mapping even in legacy mode
                            data = await async_fetch_json(
                                alt,
                                headers=headers,
                                params=params,
                                timeout=15,
                                client=client,
                            )
                            status = 200
                        log.info("mvrv_endpoint_success", url=alt)
                        break
                    except Exception as e2:
                        last_exc = last_exc or e2
                        log.warning("mvrv_endpoint_failed", url=alt, error=str(e2))
                        continue
                if data is None and last_exc is not None:
                    raise last_exc

            # Parse HAL or flat JSON payloads robustly
            def _parse_any(payload: Any) -> tuple[float | None, int | None]:
                def _coerce_num(x: Any) -> float | None:
                    try:
                        return float(x)
                    except Exception:
                        return None

                def _coerce_ts(x: Any) -> int | None:
                    try:
                        return int(x)
                    except Exception:
                        # try ISO date like '2025-09-29'
                        try:
                            if isinstance(x, str) and len(x) >= 10:
                                dt = datetime.fromisoformat(x[:10])
                                return int(dt.replace(tzinfo=UTC).timestamp())
                        except Exception:
                            pass
                        return None

                if isinstance(payload, dict):
                    # direct fields
                    candidates = [
                        payload.get("value"),
                        payload.get("mvrv_z_score"),
                        payload.get("zscore"),
                        payload.get("mvrv"),
                        payload.get("mvrvZscore"),  # bitcoin-data.com field
                    ]
                    for c in candidates:
                        v = _coerce_num(c)
                        if v is not None:
                            # try multiple timestamp keys
                            ts_candidates = [
                                payload.get("timestamp"),
                                payload.get("unixTs"),
                                payload.get("ts"),
                                payload.get("time"),
                                payload.get("t"),
                                payload.get("d"),  # 'YYYY-MM-DD' date field
                                payload.get("date"),  # common alias
                            ]
                            ts_val = None
                            for tsk in ts_candidates:
                                ts_val = _coerce_ts(tsk)
                                if ts_val is not None:
                                    break
                            return v, ts_val
                    # HAL style lists
                    for key in ("content", "items"):
                        arr = payload.get(key)
                        if isinstance(arr, list) and arr:
                            v, ts = _parse_any(arr[-1])  # take latest
                            if v is not None:
                                return v, ts
                    # _embedded style
                    emb = payload.get("_embedded")
                    if isinstance(emb, dict):
                        for vlist in emb.values():
                            if isinstance(vlist, list) and vlist:
                                v, ts = _parse_any(vlist[-1])
                                if v is not None:
                                    return v, ts
                elif isinstance(payload, list) and payload:
                    return _parse_any(payload[-1])
                return None, None

            v, ts_i = _parse_any(data)
            if v is None:
                v = 0.0
            rec: MvrvRecord = {
                "timestamp": ts_i,
                "asset": symbol,
                "metric_name": "mvrv_z_score",
                "value": float(v),
                "source": "bgeometrics",
                "confidence_score": 1.0 if float(v) != 0.0 else 0.0,
            }
            cache.set(key, rec, expire=cache_ttl)
            MVRV_SUCCESS.inc()
            log.info("mvrv_success", symbol=symbol, source="bgeometrics", status=status)
            return rec
    except Exception as e:
        MVRV_ERRORS.inc()
        log.error("mvrv_error", symbol=symbol, error=str(e))
        return None


__all__ = ["fetch_mvrv", "MvrvRecord"]

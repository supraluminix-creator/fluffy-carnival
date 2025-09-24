"""Collectors Binance (spot & futures) avec API publique.

Feature flags (env):
  BINANCE_HTTP_TIMEOUT (float, défaut 5s)

Fonctions exposées:
  fetch_binance_spot_price(symbol)
  fetch_binance_futures_oi(symbol)
  fetch_binance_funding(symbol)
"""
from __future__ import annotations

import os
from pipeline.flags import is_forced_facade, is_dry_run_facade
import time
from typing import Optional, Dict, Any

import httpx
from pipeline.http import fetch_json  # façade unifiée pour mode forcé
from prometheus_client import Counter, REGISTRY as PROM_REGISTRY
from pipeline.utils import to_float
from pipeline.metrics import FACADE_FORCED
from pipeline.metrics.collectors import mark_legacy_http, set_facade_mode
from pipeline.metrics import COLLECTOR_ERROR_TYPES_TOTAL
from pipeline.errors import (
    classify,
    RateLimitError,
    NotFoundError,
    NetworkError,
    TimeoutError_,
    SchemaError,
    UpstreamError,
    EmptyDataError,
)
import structlog

logger = structlog.get_logger(__name__)

BINANCE_SPOT_BASE = "https://api.binance.com"
BINANCE_FUTURES_BASE = "https://fapi.binance.com"

_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "5"))
_LEGACY_LOGGED: set[str] = set()

# Compteur usage HTTP legacy (chemins directs httpx.get non migrés vers façade)
try:  # idempotent pour tests
    LEGACY_HTTP_USAGE = Counter('legacy_http_usage_total', 'Legacy HTTP usage by collector', ['collector'])
except ValueError:  # déjà enregistré
    LEGACY_HTTP_USAGE = PROM_REGISTRY._names_to_collectors.get('legacy_http_usage_total')  # type: ignore[attr-defined]
try:
    # Initialise échantillon pour binance (spot) afin de figer la famille même sans inc
    LEGACY_HTTP_USAGE.labels(collector='binance_spot')  # type: ignore[call-arg]
except Exception:  # pragma: no cover
    pass


def _http_get(url: str, params: dict | None = None, timeout: float | None = None) -> dict:
    """Wrapper HTTP synchrone avec mapping d'erreurs -> exceptions typées.

    Ne lève que des CollectorError (ou sous-classes) pour uniformiser la classification.
    """
    timeout = timeout or _DEFAULT_TIMEOUT
    try:
        r = httpx.get(url, params=params, timeout=timeout)
    except httpx.TimeoutException as e:  # pragma: no cover - conditions réseau
        raise TimeoutError_(str(e)) from e
    except httpx.RequestError as e:  # erreurs de transport
        raise NetworkError(str(e)) from e
    status = getattr(r, "status_code", 0)
    if status == 429:
        raise RateLimitError(f"HTTP 429 {url}")
    if status == 404:
        raise NotFoundError(f"HTTP 404 {url}")
    if 500 <= status < 600:
        raise UpstreamError(f"HTTP {status} {url}")
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:  # pragma: no cover
        # Autres statuts inattendus
        raise UpstreamError(str(e)) from e
    try:
        data = r.json()
    except ValueError as e:  # JSON decode
        raise SchemaError(f"invalid_json:{e}") from e
    if data in (None, {}, []):
        raise EmptyDataError("empty_payload")
    return data


def _ts_ms() -> int:
    return int(time.time() * 1000)


def fetch_binance_spot_price(symbol: str) -> Optional[Dict[str, Any]]:
    """Retourne le prix spot symbol ex: BTCUSDT.

    Mode forced façade (FORCE_HTTP_FACADE=1) : utilise fetch_json (unifié) sans incrément legacy.
    Sinon conserve le chemin legacy instrumenté.
    """
    url = f"{BINANCE_SPOT_BASE}/api/v3/ticker/price"
    force_facade = is_forced_facade()
    dry_run = is_dry_run_facade() and not force_facade
    set_facade_mode("binance_spot", force_facade, dry_run)
    if force_facade:  # reset état legacy pour invariants tests
        _LEGACY_LOGGED.discard('binance_spot')
    try:
        if force_facade:
            data = fetch_json(url, params={"symbol": symbol.upper()}, timeout=_DEFAULT_TIMEOUT)
        else:
            try:  # instrumentation legacy HTTP direct
                mark_legacy_http('binance_spot')
                if "binance_spot" not in _LEGACY_LOGGED:
                    logger.info("legacy_http_usage_detected", collector="binance_spot")
                    _LEGACY_LOGGED.add("binance_spot")
            except Exception:  # pragma: no cover
                pass
            data = _http_get(url, params={"symbol": symbol.upper()})
        if "price" not in data:
            raise SchemaError("missing_price_field")
        price = to_float(data.get("price"))
        return {
            "timestamp": _ts_ms(),
            "asset": symbol[:-4],
            "symbol": symbol.upper(),
            "metric_name": "spot_price_usdt",
            "value": price,
            "source": "binance_spot",
            "confidence_score": 0.9,
        }
    except Exception as e:
        et = classify(e)
        try:
            COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="binance_spot", error_type=et).inc()
        except Exception:  # pragma: no cover
            pass
        logger.warning("binance_spot_error", symbol=symbol, error=str(e), error_type=et, symbol_pair=symbol.upper(), forced=force_facade)
        return None


def fetch_binance_futures_oi(symbol: str) -> Optional[Dict[str, Any]]:
    """Open interest (USD-M futures). Support forced façade."""
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/openInterest"
    force_facade = is_forced_facade()
    dry_run = is_dry_run_facade() and not force_facade
    set_facade_mode("binance_oi", force_facade, dry_run)
    if force_facade:
        _LEGACY_LOGGED.discard('binance_oi')
    try:
        if force_facade:
            data = fetch_json(url, params={"symbol": symbol.upper()}, timeout=_DEFAULT_TIMEOUT)
        else:
            try:
                mark_legacy_http('binance_oi')
                if "binance_oi" not in _LEGACY_LOGGED:
                    logger.info("legacy_http_usage_detected", collector="binance_oi")
                    _LEGACY_LOGGED.add("binance_oi")
            except Exception:  # pragma: no cover
                pass
            data = _http_get(url, params={"symbol": symbol.upper()})
        oi = to_float(data.get("openInterest"))
        return {
            "timestamp": _ts_ms(),
            "asset": symbol[:-4],
            "symbol": symbol.upper(),
            "metric_name": "open_interest",
            "value": oi,
            "source": "binance",
            "confidence_score": 0.85,
        }
    except Exception as e:
        et = classify(e)
        try:
            COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="binance_oi", error_type=et).inc()
        except Exception:  # pragma: no cover
            pass
        logger.warning("binance_oi_error", symbol=symbol, error=str(e), error_type=et, symbol_pair=symbol.upper(), forced=force_facade)
        return None


def fetch_binance_funding(symbol: str) -> Optional[Dict[str, Any]]:
    """Funding rate (dernier enregistrement). Support forced façade."""
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/fundingRate"
    force_facade = is_forced_facade()
    dry_run = is_dry_run_facade() and not force_facade
    set_facade_mode("binance_funding", force_facade, dry_run)
    if force_facade:
        _LEGACY_LOGGED.discard('binance_funding')
    try:
        if force_facade:
            data = fetch_json(url, params={"symbol": symbol.upper(), "limit": 1}, timeout=_DEFAULT_TIMEOUT)
        else:
            try:
                mark_legacy_http('binance_funding')
                if "binance_funding" not in _LEGACY_LOGGED:
                    logger.info("legacy_http_usage_detected", collector="binance_funding")
                    _LEGACY_LOGGED.add("binance_funding")
            except Exception:  # pragma: no cover
                pass
            data = _http_get(url, params={"symbol": symbol.upper(), "limit": 1})
        if not data:
            return None
        entry = data[0]
        fr = to_float(entry.get("fundingRate"))
        try:
            ts = int(entry.get("fundingTime", _ts_ms()))
        except (TypeError, ValueError):
            ts = _ts_ms()
        return {
            "timestamp": ts,
            "asset": symbol[:-4],
            "symbol": symbol.upper(),
            "metric_name": "funding_rate",
            "value": fr,
            "source": "binance",
            "confidence_score": 0.8,
        }
    except Exception as e:
        et = classify(e)
        try:
            COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="binance_funding", error_type=et).inc()
        except Exception:  # pragma: no cover
            pass
        logger.warning("binance_funding_error", symbol=symbol, error=str(e), error_type=et, symbol_pair=symbol.upper(), forced=force_facade)
        return None


__all__ = [
    "fetch_binance_spot_price",
    "fetch_binance_futures_oi",
    "fetch_binance_funding",
    # Plus d'export explicite de l'ancienne erreur interne supprimée
]

# --- Simple price collector (utilisé par tests historiques) ---
from typing import Callable, TypedDict


class BinancePriceRecord(TypedDict):
    timestamp: int
    asset: str
    metric_name: str
    value: float
    source: str
    confidence_score: float


def fetch_binance_price(
    symbol: str = "BTCUSDT",
    *,
    client_factory: Callable[[], httpx.Client] | None = None,
    api_key: str | None = None,
) -> BinancePriceRecord | None:
    """Compat helper pour tests existants (spot price simple).

    Renvoie un enregistrement avec metric_name="price". Préfèrer fetch_binance_spot_price
    pour usage pipeline (schema spot_price_usdt)."""
    api_key = api_key or os.getenv("BINANCE_API_KEY", "")
    factory = client_factory or (lambda: httpx.Client())
    url = f"{BINANCE_SPOT_BASE}/api/v3/ticker/price"
    params = {"symbol": symbol.upper()}
    headers: dict[str, str] = {}
    if api_key:
        headers["X-MBX-APIKEY"] = api_key
    try:
        with factory() as client:
            resp = client.get(url, params=params, headers=headers or None, timeout=_DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict) or "price" not in data:
                logger.warning("binance_price_invalid", symbol=symbol)
                return None
            try:
                price_f = float(data["price"])
            except (TypeError, ValueError):
                price_f = 0.0
            return BinancePriceRecord(
                timestamp=int(time.time()),
                asset=symbol.upper(),
                metric_name="price",
                value=price_f,
                source="binance",
                confidence_score=1.0 if price_f > 0 else 0.2,
            )
    except Exception as e:  # pragma: no cover
        logger.error("binance_price_error", symbol=symbol, error=str(e))
        return None

__all__.append("fetch_binance_price")

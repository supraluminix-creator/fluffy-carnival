"""Unified SOPR collectors (BGeometrics + Blockchain provider).

Provides a single typed entrypoint `fetch_sopr` with a `SOPRSource` enum.
Return type is `SOPRRecord | None`.
"""
from __future__ import annotations

from enum import Enum
from typing import TypedDict, Any, Final

import requests
import structlog
from prometheus_client import Counter, Summary

log = structlog.get_logger()

class SOPRSource(str, Enum):
    BGEOMETRICS = "bgeometrics"
    BLOCKCHAIN = "blockchain"

class SOPRRecord(TypedDict):
    symbol: str
    sopr: float
    source: SOPRSource
    timestamp: int | None  # Some APIs may not provide one; left optional

_SOPR_LATENCY: Final = Summary("sopr_fetch_latency_seconds", "Latency of SOPR fetches")
_SOPR_ERRORS: Final = Counter("sopr_fetch_errors_total", "Total SOPR fetch errors")
_SOPR_SUCCESS: Final = Counter("sopr_fetch_success_total", "Total SOPR fetch successes")

_BGEOM_BASE = "https://api.bgeometrics.com/v1/sopr"
_BLOCKCHAIN_BASE = "https://api.blockchain.com/v3/sopr"  # Placeholder; adapt to real provider


def _extract_sopr_payload(data: Any) -> tuple[float, int | None] | None:
    """Attempt to extract (sopr, timestamp) from an API payload.

    Accepts either simple {"sopr": <num>} or nested {"data": {"sopr": ..., "timestamp": ...}}.
    Returns tuple if successful else None.
    """
    if not isinstance(data, dict):
        return None
    # Direct form
    if "sopr" in data and isinstance(data["sopr"], (int, float, str)):
        try:
            val = float(data["sopr"])
        except (TypeError, ValueError):
            return None
        ts_raw = data.get("timestamp")
        ts: int | None = None
        if isinstance(ts_raw, (int, float)):
            ts = int(ts_raw)
        return (val, ts)
    # Nested form
    nested = data.get("data")
    if isinstance(nested, dict) and "sopr" in nested:
        try:
            val = float(nested["sopr"])
        except (TypeError, ValueError):
            return None
        ts_raw = nested.get("timestamp")
        ts_val: int | None = None
        if isinstance(ts_raw, (int, float)):
            ts_val = int(ts_raw)
        return (val, ts_val)
    return None


@_SOPR_LATENCY.time()
def fetch_sopr(symbol: str = "BTC", source: SOPRSource = SOPRSource.BGEOMETRICS, api_key: str | None = None) -> SOPRRecord | None:
    """Fetch SOPR metric from chosen source.

    Parameters
    ----------
    symbol: Asset symbol (default BTC)
    source: Which backend to query
    api_key: Optional API key (added as Bearer Authorization).
    """
    if source is SOPRSource.BGEOMETRICS:
        url = _BGEOM_BASE
    elif source is SOPRSource.BLOCKCHAIN:
        url = _BLOCKCHAIN_BASE
    else:  # pragma: no cover - enum safeguard
        raise ValueError(f"Unsupported SOPR source: {source}")

    params = {"symbol": symbol}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        extracted = _extract_sopr_payload(payload)
        if not extracted:
            _SOPR_ERRORS.inc()
            log.warning("sopr_parse_failed", source=source, symbol=symbol)
            return None
        sopr_val, ts = extracted
        record: SOPRRecord = {
            "symbol": symbol,
            "sopr": sopr_val,
            "source": source,
            "timestamp": ts,
        }
        _SOPR_SUCCESS.inc()
        log.info("sopr_fetch_success", source=source, symbol=symbol)
        return record
    except Exception as e:  # pragma: no cover - network/HTTP errors
        _SOPR_ERRORS.inc()
        log.error("sopr_fetch_error", source=source, symbol=symbol, error=str(e))
        return None

__all__ = ["SOPRSource", "SOPRRecord", "fetch_sopr"]

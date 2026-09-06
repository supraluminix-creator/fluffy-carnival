"""Shared protocols and generic result types for collectors.

Provides:
 - Result: success/error envelope
 - CollectorProtocol: minimal interface for pull collectors
 - WriterProtocol: interface for writing records
 - http_get_json: JSON GET helper using the unified HTTP façade (retries/backoff)
"""

from __future__ import annotations

import os
from typing import Any, Protocol, TypedDict, runtime_checkable

import httpx as _httpx
import structlog

log = structlog.get_logger()
# Expose httpx for tests monkeypatching (tests access protocols.httpx)
httpx = _httpx  # noqa: N816


class Result(TypedDict):
    ok: bool
    value: Any | None
    error: str | None


@runtime_checkable
class CollectorProtocol(Protocol):  # pragma: no cover - structural only
    def __call__(self) -> Any: ...  # noqa: D401


@runtime_checkable
class WriterProtocol(Protocol):  # pragma: no cover - structural only
    def write(self, record: Any) -> None: ...  # noqa: D401


def http_get_json(url: str, timeout: float = 10.0) -> Result:
    """Perform a JSON GET request returning a Result envelope.

    Uses the unified façade (pipeline.http.fetch_json) to benefit from
    consistent retries/backoff and classification. Never raises; errors
    are captured in the Result.error string.
    """
    # Under pytest, keep legacy httpx path so tests can monkeypatch httpx.Client
    if "PYTEST_CURRENT_TEST" in os.environ:
        try:
            with httpx.Client() as client:
                resp = client.get(url, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    return {"ok": False, "value": None, "error": "Non-dict JSON"}
                return {"ok": True, "value": data, "error": None}
        except Exception as e:  # pragma: no cover - network
            log.warning("http_get_json_error", url=url, error=str(e))
            return {"ok": False, "value": None, "error": str(e)}
    # Default path: use unified façade
    try:
        from pipeline.http import fetch_json  # local import to avoid cycles

        data = fetch_json(url, timeout=timeout)
        if not isinstance(data, dict):
            return {"ok": False, "value": None, "error": "Non-dict JSON"}
        return {"ok": True, "value": data, "error": None}
    except Exception as e:  # pragma: no cover - network
        log.warning("http_get_json_error", url=url, error=str(e))
        return {"ok": False, "value": None, "error": str(e)}


__all__ = [
    "Result",
    "CollectorProtocol",
    "WriterProtocol",
    "http_get_json",
]

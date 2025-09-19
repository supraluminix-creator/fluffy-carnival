"""Shared protocols and generic result types for collectors.

Provides:
 - Result[T]: success/error envelope
 - CollectorProtocol: minimal interface for pull collectors
 - WriterProtocol: interface for writing records
 - http_get_json: thin wrapper around httpx for JSON GET with timeout
"""
from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar, TypedDict, runtime_checkable
import httpx
import structlog

log = structlog.get_logger()

T = TypeVar("T")


class Result(TypedDict, Generic[T]):
    ok: bool
    value: T | None
    error: str | None


@runtime_checkable
class CollectorProtocol(Protocol):  # pragma: no cover - structural only
    def __call__(self) -> Any: ...  # noqa: D401


@runtime_checkable
class WriterProtocol(Protocol):  # pragma: no cover - structural only
    def write(self, record: Any) -> None: ...  # noqa: D401


def http_get_json(url: str, timeout: float = 10.0) -> Result[dict[str, Any]]:
    """Perform a JSON GET request returning a Result envelope.

    Never raises; network / parse errors captured in error string.
    """
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

__all__ = [
    "Result",
    "CollectorProtocol",
    "WriterProtocol",
    "http_get_json",
]

"""Client HTTP partagé avec backoff exponentiel simple.

DEPRECATED: utiliser `pipeline.http.fetch_json` / `pipeline.http.async_fetch_json` qui
reposent sur `http_wrappers` (breaker, classification, métriques unified) et
gèrent retries/budget de manière cohérente. Ce module est conservé provisoirement
pour compatibilité mais sera retiré après migration complète.

Expose:
 - get_json (sync)
 - aget_json (async)
 - get_async_client (réutilisation pool)
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Enhanced client configuration for persistent pooling
CLIENT_LIMITS = httpx.Limits(
    max_connections=100,           # Total concurrent connections
    max_keepalive_connections=20,  # Keep-alive connections
    keepalive_expiry=30.0,         # Keep-alive timeout
)

CLIENT_TIMEOUT = httpx.Timeout(
    timeout=10.0,      # Default timeout
    connect=5.0,       # Connection timeout
    read=10.0,         # Read timeout
    write=5.0,         # Write timeout
    pool=5.0,          # Pool timeout
)

_ASYNC_CLIENT: httpx.AsyncClient | None = None
_SYNC_CLIENT: httpx.Client | None = None

DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 4
RETRY_STATUS = {429, 500, 502, 503, 504}


def get_sync_client() -> httpx.Client:
    global _SYNC_CLIENT
    if _SYNC_CLIENT is None:
        _SYNC_CLIENT = httpx.Client(timeout=DEFAULT_TIMEOUT)
    return _SYNC_CLIENT


def get_async_client() -> httpx.AsyncClient:
    global _ASYNC_CLIENT
    if _ASYNC_CLIENT is None:
        # Initialize with optimized settings for persistent pooling
        _ASYNC_CLIENT = httpx.AsyncClient(
            limits=CLIENT_LIMITS,
            timeout=CLIENT_TIMEOUT,
            follow_redirects=True,
        )
    return _ASYNC_CLIENT


@asynccontextmanager
async def get_http_client(**overrides: Any) -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    Context manager providing a shared httpx.AsyncClient with optimized persistent pooling.

    Usage:
        async with get_http_client() as client:
            response = await client.get('https://api.example.com')

    Args:
        **overrides: Override default client settings (limits, timeout, etc.)
    """
    client = get_async_client()

    # Apply overrides if provided
    if overrides:
        # Create a temporary client with overrides
        temp_client = httpx.AsyncClient(
            limits=CLIENT_LIMITS,
            timeout=CLIENT_TIMEOUT,
            follow_redirects=True,
            **overrides
        )
        try:
            yield temp_client
        finally:
            await temp_client.aclose()
    else:
        # Use shared client
        yield client


def _backoff(attempt: int) -> float:
    val = 0.25 * (2 ** (attempt - 1)) + float(random.uniform(0, 0.25))
    return float(min(val, 5.0))


def _retryable(exc: Exception, status: int | None) -> bool:
    if status in RETRY_STATUS:
        return True
    name = type(exc).__name__.lower()
    return any(k in name for k in ("timeout", "connect", "network", "proxy"))


def _backoff(attempt: int) -> float:
    val = 0.25 * (2 ** (attempt - 1)) + float(random.uniform(0, 0.25))
    return float(min(val, 5.0))


def _retryable(exc: Exception, status: int | None) -> bool:
    if status in RETRY_STATUS:
        return True
    name = type(exc).__name__.lower()
    return any(k in name for k in ("timeout", "connect", "network", "proxy"))


def get_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
) -> Any:  # pragma: no cover - legacy path
    client = get_sync_client()
    attempt = 1
    while True:
        try:
            r = client.get(url, headers=headers, params=params)
            if r.status_code in RETRY_STATUS and attempt < MAX_RETRIES:
                b = _backoff(attempt)
                logger.warning(
                    "retry_sync_status url=%s status=%s attempt=%s backoff=%s",
                    url,
                    r.status_code,
                    attempt,
                    b,
                )
                attempt += 1
                # sleep synchronously (ne pas utiliser asyncio.sleep dans contexte sync)
                from contextlib import suppress

                with suppress(Exception):  # pragma: no cover
                    time.sleep(b)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            if attempt < MAX_RETRIES and _retryable(e, status):
                b = _backoff(attempt)
                logger.warning(
                    "retry_sync_exc url=%s attempt=%s backoff=%s error=%s",
                    url,
                    attempt,
                    b,
                    str(e),
                )
                attempt += 1
                from contextlib import suppress

                with suppress(Exception):  # pragma: no cover
                    time.sleep(b)
                continue
            raise


async def aget_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
) -> Any:  # pragma: no cover - legacy path
    client = get_async_client()
    attempt = 1
    while True:
        try:
            r = await client.get(url, headers=headers, params=params)
            if r.status_code in RETRY_STATUS and attempt < MAX_RETRIES:
                b = _backoff(attempt)
                logger.warning(
                    "retry_async_status url=%s status=%s attempt=%s backoff=%s",
                    url,
                    r.status_code,
                    attempt,
                    b,
                )
                attempt += 1
                await asyncio.sleep(b)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            if attempt < MAX_RETRIES and _retryable(e, status):
                b = _backoff(attempt)
                logger.warning("retry_async_exc url=%s attempt=%s backoff=%s error=%s", url, attempt, b, str(e))
                attempt += 1
                await asyncio.sleep(b)
                continue
            raise


async def aclose() -> None:  # pragma: no cover
    global _ASYNC_CLIENT
    if _ASYNC_CLIENT is not None:
        await _ASYNC_CLIENT.aclose()
        _ASYNC_CLIENT = None


async def close_http_client() -> None:
    """Close the global HTTP client (for cleanup)."""
    await aclose()


def get_client_config() -> dict[str, Any]:
    """Get current client configuration for debugging."""
    return {
        "limits": {
            "max_connections": CLIENT_LIMITS.max_connections,
            "max_keepalive_connections": CLIENT_LIMITS.max_keepalive_connections,
            "keepalive_expiry": CLIENT_LIMITS.keepalive_expiry,
        },
        "timeout": {
            "timeout": CLIENT_TIMEOUT.timeout,
            "connect": CLIENT_TIMEOUT.connect,
            "read": CLIENT_TIMEOUT.read,
            "write": CLIENT_TIMEOUT.write,
            "pool": CLIENT_TIMEOUT.pool,
        },
        "has_global_client": _ASYNC_CLIENT is not None,
    }

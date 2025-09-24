"""Façade HTTP unifiée (sync & async)

Objectifs quick-win:
 - Point d'entrée unique pour les collectors: fetch_json / async_fetch_json
 - Paramètres homogènes (timeout, retries, backoff_base, headers, params)
 - Réutilise la logique robuste existante de `http_wrappers` (retry, breaker, classification, métriques)
 - Permet déprécation progressive de `http_client.py` (backoff simple) sans rupture

Politique de retry:
 - Par défaut on respecte l'env `RETRY_HTTP_ENABLED` (activé par défaut) + variables:
   * RETRY_HTTP_MAX (int, défaut 3)
   * RETRY_HTTP_BACKOFF_BASE (float, défaut 0.3)
   * RETRY_MAX_CUMULATIVE_SLEEP_SEC (float, 0 = illimité)
 - Paramètres explicites `retries` / `backoff_base` dans l'appel priment sur l'env.

Exemple:
 >>> from pipeline.http import fetch_json
 >>> data = fetch_json("https://api.coingecko.com/api/v3/ping")

Async:
 >>> import asyncio
 >>> from pipeline.http import async_fetch_json
 >>> asyncio.run(async_fetch_json("https://api.llama.fi/chains"))
"""
from __future__ import annotations

from typing import Any, Mapping
import httpx
import os

from . import http_wrappers

__all__ = [
    "fetch_json",
    "async_fetch_json",
]


def fetch_json(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    retries: int | None = None,
    backoff_base: float | None = None,
) -> Any:
    """Fetch JSON (sync) avec retry/breaker.

    Utilise `http_wrappers.http_get_json_retry` si retries > 0 ou si RETRY_HTTP_ENABLED=1.
    Fallback vers `http_wrappers.http_get_json` sans retry.
    """
    if retries is None:
        # Décide via env
        enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
        if not enabled:
            return http_wrappers.http_get_json(url, timeout=timeout, headers=headers, params=params)
        retries = int(os.getenv("RETRY_HTTP_MAX", "3"))
    if backoff_base is None:
        backoff_base = float(os.getenv("RETRY_HTTP_BACKOFF_BASE", "0.3"))
    if retries <= 0:
        return http_wrappers.http_get_json(url, timeout=timeout, headers=headers, params=params)
    return http_wrappers.http_get_json_retry(
        url,
        timeout=timeout,
        headers=headers,
        params=params,
        retries=retries,
        backoff_base=backoff_base,
        classify_endpoint=http_wrappers.endpoint_label,
    )


async def async_fetch_json(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    retries: int | None = None,
    backoff_base: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> Any:
    """Version asynchrone.

    Option `client` pour réutilisation pooling; sinon client éphémère.
    """
    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout or http_wrappers.DEFAULT_TIMEOUT)
        own_client = True
    try:
        if retries is None:
            enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
            if not enabled:
                return await http_wrappers.async_http_get_json(client, url, timeout=timeout, headers=headers, params=params)
            retries = int(os.getenv("RETRY_HTTP_MAX", "3"))
        if backoff_base is None:
            backoff_base = float(os.getenv("RETRY_HTTP_BACKOFF_BASE", "0.3"))
        if retries <= 0:
            return await http_wrappers.async_http_get_json(client, url, timeout=timeout, headers=headers, params=params)
        return await http_wrappers.async_http_get_json_retry(
            client,
            url,
            timeout=timeout,
            headers=headers,
            params=params,
            retries=retries,
            backoff_base=backoff_base,
            classify_endpoint=http_wrappers.endpoint_label,
        )
    finally:
        if own_client:
            try:
                await client.aclose()
            except Exception:  # pragma: no cover
                pass

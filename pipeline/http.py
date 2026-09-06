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

import os
from collections.abc import Mapping
from typing import Any, cast

import httpx

from . import http_wrappers

__all__ = [
    "fetch_json",
    "async_fetch_json",
    "post_json",
    "async_post_json",
    "fetch_text",
    "async_fetch_text",
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
        http_client = cast(http_wrappers.AsyncHttpClient, client)
        if retries is None:
            enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
            if not enabled:
                return await http_wrappers.async_http_get_json(
                    http_client,
                    url,
                    timeout=timeout,
                    headers=headers,
                    params=params,
                )
            retries = int(os.getenv("RETRY_HTTP_MAX", "3"))
        if backoff_base is None:
            backoff_base = float(os.getenv("RETRY_HTTP_BACKOFF_BASE", "0.3"))
        if retries <= 0:
            return await http_wrappers.async_http_get_json(
                http_client,
                url,
                timeout=timeout,
                headers=headers,
                params=params,
            )
        return await http_wrappers.async_http_get_json_retry(
            http_client,
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
            from contextlib import suppress

            with suppress(Exception):  # pragma: no cover
                await client.aclose()


def post_json(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any | None = None,
    data: Any | None = None,
    retries: int | None = None,
    backoff_base: float | None = None,
) -> Any:
    """POST JSON (sync) avec retry/breaker optionnels.

    Respecte RETRY_HTTP_ENABLED/RETRY_HTTP_MAX/RETRY_HTTP_BACKOFF_BASE quand retries/backoff_base non fournis.
    """
    if retries is None:
        enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
        if not enabled:
            return http_wrappers.http_post_json(url, timeout=timeout, headers=headers, json=json, data=data)
        retries = int(os.getenv("RETRY_HTTP_MAX", "3"))
    if backoff_base is None:
        backoff_base = float(os.getenv("RETRY_HTTP_BACKOFF_BASE", "0.3"))
    if retries <= 0:
        return http_wrappers.http_post_json(url, timeout=timeout, headers=headers, json=json, data=data)
    return http_wrappers.http_post_json_retry(
        url,
        timeout=timeout,
        headers=headers,
        json=json,
        data=data,
        retries=retries,
        backoff_base=backoff_base,
        classify_endpoint=http_wrappers.endpoint_label,
    )


async def async_post_json(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any | None = None,
    data: Any | None = None,
    retries: int | None = None,
    backoff_base: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> Any:
    """POST JSON (async) avec retry/breaker optionnels."""
    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout or http_wrappers.DEFAULT_TIMEOUT)
        own_client = True
    try:
        http_client = cast(http_wrappers.AsyncHttpClient, client)
        if retries is None:
            enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
            if not enabled:
                return await http_wrappers.async_http_post_json(
                    http_client, url, timeout=timeout, headers=headers, json=json, data=data
                )
            retries = int(os.getenv("RETRY_HTTP_MAX", "3"))
        if backoff_base is None:
            backoff_base = float(os.getenv("RETRY_HTTP_BACKOFF_BASE", "0.3"))
        if retries <= 0:
            return await http_wrappers.async_http_post_json(
                http_client, url, timeout=timeout, headers=headers, json=json, data=data
            )
        return await http_wrappers.async_http_post_json_retry(
            http_client,
            url,
            timeout=timeout,
            headers=headers,
            json=json,
            data=data,
            retries=retries,
            backoff_base=backoff_base,
            classify_endpoint=http_wrappers.endpoint_label,
        )
    finally:
        if own_client:
            from contextlib import suppress

            with suppress(Exception):  # pragma: no cover
                await client.aclose()


def fetch_text(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    retries: int | None = None,
    backoff_base: float | None = None,
) -> str:
    """GET texte (sync) avec retry optionnel."""
    if retries is None:
        enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
        if not enabled:
            return http_wrappers.http_get_text(url, timeout=timeout, headers=headers, params=params)
        retries = int(os.getenv("RETRY_HTTP_MAX", "3"))
    if backoff_base is None:
        backoff_base = float(os.getenv("RETRY_HTTP_BACKOFF_BASE", "0.3"))
    if retries <= 0:
        return http_wrappers.http_get_text(url, timeout=timeout, headers=headers, params=params)
    return http_wrappers.http_get_text_retry(
        url,
        timeout=timeout,
        headers=headers,
        params=params,
        retries=retries,
        backoff_base=backoff_base,
        classify_endpoint=http_wrappers.endpoint_label,
    )


async def async_fetch_text(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    retries: int | None = None,
    backoff_base: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """GET texte (async) avec retry optionnel."""
    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout or http_wrappers.DEFAULT_TIMEOUT)
        own_client = True
    try:
        http_client = cast(http_wrappers.AsyncHttpClient, client)
        if retries is None:
            enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
            if not enabled:
                return await http_wrappers.async_http_get_text(
                    http_client, url, timeout=timeout, headers=headers, params=params
                )
            retries = int(os.getenv("RETRY_HTTP_MAX", "3"))
        if backoff_base is None:
            backoff_base = float(os.getenv("RETRY_HTTP_BACKOFF_BASE", "0.3"))
        if retries <= 0:
            return await http_wrappers.async_http_get_text(
                http_client,
                url,
                timeout=timeout,
                headers=headers,
                params=params,
            )
        return await http_wrappers.async_http_get_text_retry(
            http_client,
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
            from contextlib import suppress

            with suppress(Exception):  # pragma: no cover
                await client.aclose()

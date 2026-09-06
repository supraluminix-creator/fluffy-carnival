"""Wrappers HTTP centralisés (sync/async) avec classification d'erreurs.

Objectifs:
  - Réduction duplication parsing / mapping status -> exceptions typées
  - Point unique pour futures améliorations (retry, backoff, instrumentation fine)
"""

from __future__ import annotations

# Déclaration explicite de __all__ (évite les type: ignore inutiles)
__all__: list[str] = []

import os
import random
import time
from collections import deque
from collections.abc import Callable, Mapping
from contextlib import suppress
from types import TracebackType
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import httpx
import structlog

from .rate_limit import build_rate_limiter_from_env

try:  # pragma: no cover - metrics import defensive
    from .metrics import (
        HTTP_BREAKER_OPEN_SECONDS,
        HTTP_BREAKER_OPENS_TOTAL,
        HTTP_BREAKER_SKIPS_TOTAL,
        HTTP_BREAKER_STATE,
        HTTP_RETRIES_TOTAL,
        HTTP_RETRY_ATTEMPT_LATENCY_SECONDS,
        RETRY_BUDGET_EXHAUSTED_TOTAL,
        RETRY_BUDGET_REMAINING_SECONDS,
    )
except Exception:  # pragma: no cover
    HTTP_RETRIES_TOTAL = None
    HTTP_RETRY_ATTEMPT_LATENCY_SECONDS = None
    HTTP_BREAKER_OPENS_TOTAL = None
    HTTP_BREAKER_SKIPS_TOTAL = None
    HTTP_BREAKER_STATE = None
    HTTP_BREAKER_OPEN_SECONDS = None
    RETRY_BUDGET_REMAINING_SECONDS = None
    RETRY_BUDGET_EXHAUSTED_TOTAL = None

# (Ancien RUNTIME_RETRY_COUNT retiré pour limiter le bruit; utiliser métriques Prometheus)
from .errors import (
    EmptyDataError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    SchemaError,
    TimeoutError_,
    UpstreamError,
)

logger = structlog.get_logger(__name__)

RETRIABLE_EXC = (RateLimitError, TimeoutError_, NetworkError, UpstreamError)
__all__.append("RETRIABLE_EXC")

DEFAULT_TIMEOUT = 10


class AsyncHttpClient(Protocol):
    async def get(self, url: Any, **kwargs: Any) -> Any:
        ...

    async def post(self, url: Any, **kwargs: Any) -> Any:
        ...


class SyncHttpClient(Protocol):
    def __enter__(self) -> SyncHttpClient:
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        ...

    def get(self, url: Any, **kwargs: Any) -> Any:
        ...


__all__.extend(["AsyncHttpClient", "SyncHttpClient"])

# ------------------ Throttling optionnel (par endpoint) ------------------
_HTTP_THROTTLE = None  # construit à la demande
_HTTP_THROTTLE_LIMIT = 0


def _get_http_throttle():
    """Retourne (limiter, limit) si activé; sinon (None, 0).

    Activation via HTTP_THROTTLE_PER_MIN_DEFAULT (>0). Backend: mémoire ou Redis si configuré.
    """
    global _HTTP_THROTTLE, _HTTP_THROTTLE_LIMIT
    if _HTTP_THROTTLE is not None:
        return _HTTP_THROTTLE, _HTTP_THROTTLE_LIMIT
    try:
        lim = int(os.getenv("HTTP_THROTTLE_PER_MIN_DEFAULT", "0"))
    except Exception:
        lim = 0
    _HTTP_THROTTLE_LIMIT = max(0, lim)
    _HTTP_THROTTLE = build_rate_limiter_from_env(_HTTP_THROTTLE_LIMIT) if _HTTP_THROTTLE_LIMIT > 0 else None
    return _HTTP_THROTTLE, _HTTP_THROTTLE_LIMIT


# ------------------ Endpoint labeling (réduction cardinalité) ------------------
def endpoint_label(url: str) -> str:
    """Reduce cardinality for metrics by normalizing URL.

    Rules:
      netloc + up to first 2 path segments (ignoring empty). No query string.
      Example: https://api.coingecko.com/api/v3/coins/bitcoin -> coingecko/coins
               https://api.binance.com/api/v3/depth?symbol=BTCUSDT -> binance/depth
               https://api.llama.fi/protocols -> llama/protocols
    Fallback: full url truncated 60 chars if parsing fails.
    """
    try:
        p = urlparse(url)
        host = p.hostname or "unknown"
        parts_host = [h for h in host.split(".") if h]
        # Retirer préfixes peu informatifs ('api','www') successivement
        while len(parts_host) > 1 and parts_host[0] in {"api", "www"}:
            parts_host.pop(0)
        # Heuristique: si au moins 2 segments restants (ex: coingecko com) on prend l'avant dernier
        # sinon on prend le seul segment.
        core = parts_host[-2] if len(parts_host) >= 2 else parts_host[0]
        raw_segs = [s for s in p.path.split("/") if s]
        ignore = {"api", "v1", "v2", "v3"}
        chosen = None
        for s in raw_segs:
            if s.lower() in ignore:
                continue
            chosen = s
            break
        if not chosen and raw_segs:
            chosen = raw_segs[0]
        if chosen:
            return (core + "/" + chosen).lower()[:60]
        return core.lower()[:60]
    except Exception:
        return url.split("?")[0][:60]


__all__.append("endpoint_label")

# ------------------ Breaker léger 429 ------------------
_RATE_LIMIT_EVENTS: dict[str, deque[float]] = {}
_BREAKER_OPEN_UNTIL: dict[str, float] = {}


def _breaker_should_block(ep: str, now: float) -> bool:
    until = _BREAKER_OPEN_UNTIL.get(ep)
    if until is None:
        return False
    if now < until:
        return True
    # expiration: fermer breaker (state -> 0) et supprimer entrée
    with suppress(KeyError):
        del _BREAKER_OPEN_UNTIL[ep]
    if "HTTP_BREAKER_STATE" in globals() and HTTP_BREAKER_STATE is not None:
        with suppress(Exception):  # pragma: no cover - instrumentation best-effort
            HTTP_BREAKER_STATE.labels(endpoint=ep).set(0)
            if HTTP_BREAKER_OPEN_SECONDS is not None:
                HTTP_BREAKER_OPEN_SECONDS.labels(endpoint=ep).set(0)
    return False


def _record_rate_limit_and_maybe_open(ep: str, now: float) -> None:
    import os

    window = float(os.getenv("HTTP_BREAKER_WINDOW", "30"))  # seconds
    threshold = int(os.getenv("HTTP_BREAKER_THRESHOLD", "5"))
    cooldown = float(os.getenv("HTTP_BREAKER_COOLDOWN", "20"))
    dq = _RATE_LIMIT_EVENTS.setdefault(ep, deque())
    # purge
    while dq and dq[0] < now - window:
        dq.popleft()
    dq.append(now)
    if len(dq) >= threshold:
        _BREAKER_OPEN_UNTIL[ep] = now + cooldown
        # instrumentation ouverture
        if HTTP_BREAKER_OPENS_TOTAL is not None:
            with suppress(Exception):
                HTTP_BREAKER_OPENS_TOTAL.labels(endpoint=ep).inc()
        # marquer état ouvert (state=1, open_seconds=0 initial)
        if HTTP_BREAKER_STATE is not None:
            with suppress(Exception):  # pragma: no cover - instrumentation best-effort
                HTTP_BREAKER_STATE.labels(endpoint=ep).set(1)
                HTTP_BREAKER_OPEN_SECONDS.labels(endpoint=ep).set(0)


def _map_status(status: int, url: str) -> None:
    if status == 429:
        raise RateLimitError(f"HTTP 429 {url}")
    if status == 404:
        raise NotFoundError(f"HTTP 404 {url}")
    if 500 <= status < 600:
        raise UpstreamError(f"HTTP {status} {url}")


def http_get_json(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
) -> Any:
    t = timeout or DEFAULT_TIMEOUT
    try:
        r = httpx.get(url, headers=headers, params=params, timeout=t)
    except httpx.TimeoutException as e:  # pragma: no cover
        raise TimeoutError_(str(e)) from e
    except httpx.RequestError as e:  # pragma: no cover
        raise NetworkError(str(e)) from e
    _map_status(r.status_code, url)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:  # pragma: no cover
        raise UpstreamError(str(e)) from e
    try:
        data = r.json()
    except ValueError as e:
        raise SchemaError(f"invalid_json:{e}") from e
    if data in (None, {}, []):
        raise EmptyDataError("empty_payload")
    return data


async def async_http_get_json(
    client: AsyncHttpClient,
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
) -> Any:
    t = timeout or DEFAULT_TIMEOUT
    try:
        # Certains tests utilisent un DummyAsyncClient.get(url, timeout=...) sans headers/params.
        # Pour compatibilité, n'ajoutons ces kwargs que s'ils ne sont pas None.
        get_kwargs: dict[str, Any] = {"timeout": t}
        if headers is not None:
            get_kwargs["headers"] = headers
        if params is not None:
            get_kwargs["params"] = params
        r = await client.get(url, **get_kwargs)
    except httpx.TimeoutException as e:  # pragma: no cover
        raise TimeoutError_(str(e)) from e
    except httpx.RequestError as e:  # pragma: no cover
        raise NetworkError(str(e)) from e
    # Stubs de tests peuvent ne pas fournir status_code / raise_for_status.
    status = getattr(r, "status_code", 200)
    if isinstance(status, int):
        _map_status(status, url)
        try:  # pragma: no cover - lève rarement dans tests
            if hasattr(r, "raise_for_status"):
                r.raise_for_status()
        except httpx.HTTPStatusError as e:  # pragma: no cover
            raise UpstreamError(str(e)) from e
    try:
        data = r.json() if hasattr(r, "json") else getattr(r, "_payload", None)  # pragma: no cover - fallback très rare
    except ValueError as e:
        raise SchemaError(f"invalid_json:{e}") from e
    if data in (None, {}, []):
        raise EmptyDataError("empty_payload")
    return data


__all__.extend(["http_get_json", "async_http_get_json"])


def http_get_json_retry(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    retries: int = 3,
    backoff_base: float = 0.3,
    classify_endpoint: Callable[[str], str] | None = None,
) -> Any:
    """Version résiliente avec retry/backoff exponentiel.

    Retries sur: RateLimitError, TimeoutError_, NetworkError, UpstreamError (5xx).
    Instrumente:
      - http_retries_total (endpoint, reason)
      - http_retry_attempt_latency_seconds (endpoint, attempt, final_status)
    """
    ep = classify_endpoint(url) if classify_endpoint else endpoint_label(url)
    attempt = 0
    cumulative_sleep = 0.0
    max_cumulative = float(os.getenv("RETRY_MAX_CUMULATIVE_SLEEP_SEC", "0"))  # 0 = illimité
    while True:
        attempt += 1
        start = time.perf_counter()
        final_status = "success"
        now = time.time()
        # Throttling optionnel par endpoint (avant tentative réseau)
        limiter, lim = _get_http_throttle()
        if limiter is not None and lim > 0:
            provider = (ep.split("/")[0]) if "/" in ep else ep
            allowed, wait, _rem, _reset = limiter.check_allow_with_meta(f"http:{provider}")
            if not allowed:
                max_wait = float(os.getenv("HTTP_THROTTLE_MAX_WAIT", "8"))
                sleep_for = min(max(1.0, float(wait)), max_wait)
                logger.info(
                    "http_throttle_sleep",
                    endpoint=ep,
                    provider=provider,
                    wait=wait,
                    sleep_for=sleep_for,
                )
                time.sleep(sleep_for)
                cumulative_sleep += sleep_for
                if RETRY_BUDGET_REMAINING_SECONDS is not None and max_cumulative:
                    with suppress(Exception):
                        RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(
                            max(0.0, max_cumulative - cumulative_sleep)
                        )
        if max_cumulative and cumulative_sleep >= max_cumulative:
            # Budget épuisé -> arrêter immédiatement
            logger.warning(
                "retry_budget_exhausted",
                endpoint=ep,
                attempt=attempt,
                cumulative_sleep=cumulative_sleep,
                max_cumulative=max_cumulative,
            )
            if RETRY_BUDGET_EXHAUSTED_TOTAL is not None:
                with suppress(Exception):
                    RETRY_BUDGET_EXHAUSTED_TOTAL.labels(endpoint=ep).inc()
            raise TimeoutError_(f"retry_budget_exhausted {ep} cumulative={cumulative_sleep:.2f}s > {max_cumulative}s")
        if RETRY_BUDGET_REMAINING_SECONDS is not None:
            with suppress(Exception):
                rem = -1 if max_cumulative == 0 else max(0.0, max_cumulative - cumulative_sleep)
                RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(rem)
        # Breaker open ?
        if _breaker_should_block(ep, now):
            # Simuler RateLimitError immédiat (compte comme échec final si pas de retries restants)
            err = RateLimitError(f"breaker_open {ep}")
            # instrumentation skip
            if HTTP_BREAKER_SKIPS_TOTAL is not None:
                with suppress(Exception):
                    HTTP_BREAKER_SKIPS_TOTAL.labels(endpoint=ep).inc()
            # mettre à jour temps ouvert
            until = _BREAKER_OPEN_UNTIL.get(ep)
            if until and HTTP_BREAKER_OPEN_SECONDS is not None:
                with suppress(Exception):  # pragma: no cover
                    opened_for = max(0.0, (time.time() - (until - float(os.getenv("HTTP_BREAKER_COOLDOWN", "20")))))
                    HTTP_BREAKER_OPEN_SECONDS.labels(endpoint=ep).set(opened_for)
            final_status = type(err).__name__
            if attempt > retries:
                raise err
            if HTTP_RETRIES_TOTAL is not None:
                with suppress(Exception):
                    HTTP_RETRIES_TOTAL.labels(endpoint=ep, reason=type(err).__name__).inc()
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            remaining = max_cumulative - cumulative_sleep if max_cumulative else delay
            sleep_for = min(delay, 5, remaining)
            logger.info(
                "retry_sleep",
                endpoint=ep,
                attempt=attempt,
                delay=delay,
                sleep_for=sleep_for,
                cumulative_sleep=cumulative_sleep,
                breaker_state="open",
            )
            time.sleep(sleep_for)
            cumulative_sleep += sleep_for
            if RETRY_BUDGET_REMAINING_SECONDS is not None and max_cumulative:
                with suppress(Exception):
                    RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(max(0.0, max_cumulative - cumulative_sleep))
            continue
        try:
            data = http_get_json(url, timeout=timeout, headers=headers, params=params)
            return data
        except RETRIABLE_EXC as e:
            final_status = type(e).__name__
            if isinstance(e, RateLimitError):  # compter pour breaker éventuel
                _record_rate_limit_and_maybe_open(ep, now)
                # si breaker juste ouvert un skip n'est pas enregistré ici (open == event), open_seconds déjà 0
            if attempt > retries:
                if HTTP_RETRY_ATTEMPT_LATENCY_SECONDS is not None:
                    with suppress(Exception):  # pragma: no cover
                        HTTP_RETRY_ATTEMPT_LATENCY_SECONDS.labels(
                            endpoint=ep,
                            attempt=str(attempt),
                            final_status="fail",
                        ).observe(time.perf_counter() - start)
                raise
            # enregistrer retry
            if HTTP_RETRIES_TOTAL is not None:
                with suppress(Exception):  # pragma: no cover
                    HTTP_RETRIES_TOTAL.labels(endpoint=ep, reason=type(e).__name__).inc()
            if HTTP_RETRY_ATTEMPT_LATENCY_SECONDS is not None:
                with suppress(Exception):  # pragma: no cover
                    HTTP_RETRY_ATTEMPT_LATENCY_SECONDS.labels(
                        endpoint=ep,
                        attempt=str(attempt),
                        final_status=final_status,
                    ).observe(time.perf_counter() - start)
            # backoff exponentiel + jitter
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            remaining = (max_cumulative - cumulative_sleep) if max_cumulative else delay
            if max_cumulative and remaining <= 0:
                logger.warning(
                    "retry_budget_exhausted",
                    endpoint=ep,
                    attempt=attempt,
                    cumulative_sleep=cumulative_sleep,
                    max_cumulative=max_cumulative,
                )
                raise TimeoutError_(
                    f"retry_budget_exhausted {ep} cumulative={cumulative_sleep:.2f}s > {max_cumulative}s"
                ) from e
            sleep_for = min(delay, 5, remaining)
            logger.info(
                "retry_sleep",
                endpoint=ep,
                attempt=attempt,
                delay=delay,
                sleep_for=sleep_for,
                cumulative_sleep=cumulative_sleep,
                breaker_state="closed",
            )
            time.sleep(sleep_for)
            cumulative_sleep += sleep_for
            if RETRY_BUDGET_REMAINING_SECONDS is not None and max_cumulative:
                with suppress(Exception):
                    RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(max(0.0, max_cumulative - cumulative_sleep))
            continue
        except Exception:
            # Erreurs non retriées
            if HTTP_RETRY_ATTEMPT_LATENCY_SECONDS is not None:
                with suppress(Exception):  # pragma: no cover
                    HTTP_RETRY_ATTEMPT_LATENCY_SECONDS.labels(
                        endpoint=ep,
                        attempt=str(attempt),
                        final_status="fail",
                    ).observe(time.perf_counter() - start)
            raise


__all__.append("http_get_json_retry")


def get_json_with_retry(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    timeout: float | None = None,
) -> Any:
    """Helper interne pour collectors.

    Comportement:
      - Si RETRY_HTTP_ENABLED=1 -> utilise http_get_json_retry avec paramètres:
          RETRY_HTTP_MAX (int, défaut 3)
          RETRY_HTTP_BACKOFF_BASE (float, défaut 0.3)
      - Sinon http_get_json sans retry.
    """
    import os

    if os.getenv("RETRY_HTTP_ENABLED", "1") == "1":  # activé par défaut (peut être désactivé)
        max_r = int(os.getenv("RETRY_HTTP_MAX", "3"))
        backoff = float(os.getenv("RETRY_HTTP_BACKOFF_BASE", "0.3"))
        return http_get_json_retry(
            url,
            headers=headers,
            params=params,
            timeout=timeout,
            retries=max_r,
            backoff_base=backoff,
            classify_endpoint=endpoint_label,
        )
    return http_get_json(url, headers=headers, params=params, timeout=timeout)


__all__.append("get_json_with_retry")


# ------------------ Version async retry ------------------
async def async_http_get_json_retry(
    client: AsyncHttpClient,
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    retries: int = 3,
    backoff_base: float = 0.3,
    classify_endpoint: Callable[[str], str] | None = None,
) -> Any:
    ep = classify_endpoint(url) if classify_endpoint else endpoint_label(url)
    attempt = 0
    cumulative_sleep = 0.0
    max_cumulative = float(os.getenv("RETRY_MAX_CUMULATIVE_SLEEP_SEC", "0"))
    while True:
        attempt += 1
        now = time.time()
        # Throttling optionnel par endpoint (avant tentative réseau)
        limiter, lim = _get_http_throttle()
        if limiter is not None and lim > 0:
            provider = (ep.split("/")[0]) if "/" in ep else ep
            allowed, wait, _rem, _reset = limiter.check_allow_with_meta(f"http:{provider}")
            if not allowed:
                max_wait = float(os.getenv("HTTP_THROTTLE_MAX_WAIT", "8"))
                sleep_for = min(max(1.0, float(wait)), max_wait)
                logger.info(
                    "http_throttle_sleep",
                    endpoint=ep,
                    provider=provider,
                    wait=wait,
                    sleep_for=sleep_for,
                )
                await _async_sleep(sleep_for)
                cumulative_sleep += sleep_for
                if RETRY_BUDGET_REMAINING_SECONDS is not None and max_cumulative:
                    with suppress(Exception):
                        RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(
                            max(0.0, max_cumulative - cumulative_sleep)
                        )
        if max_cumulative and cumulative_sleep >= max_cumulative:
            logger.warning(
                "retry_budget_exhausted",
                endpoint=ep,
                attempt=attempt,
                cumulative_sleep=cumulative_sleep,
                max_cumulative=max_cumulative,
            )
            if RETRY_BUDGET_EXHAUSTED_TOTAL is not None:
                with suppress(Exception):
                    RETRY_BUDGET_EXHAUSTED_TOTAL.labels(endpoint=ep).inc()
            raise TimeoutError_(f"retry_budget_exhausted {ep} cumulative={cumulative_sleep:.2f}s > {max_cumulative}s")
        if RETRY_BUDGET_REMAINING_SECONDS is not None:
            with suppress(Exception):
                rem = -1 if max_cumulative == 0 else max(0.0, max_cumulative - cumulative_sleep)
                RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(rem)
        if _breaker_should_block(ep, now):
            err = RateLimitError(f"breaker_open {ep}")
            if HTTP_BREAKER_SKIPS_TOTAL is not None:
                with suppress(Exception):
                    HTTP_BREAKER_SKIPS_TOTAL.labels(endpoint=ep).inc()
            until = _BREAKER_OPEN_UNTIL.get(ep)
            if until and HTTP_BREAKER_OPEN_SECONDS is not None:
                with suppress(Exception):
                    opened_for = max(0.0, (time.time() - (until - float(os.getenv("HTTP_BREAKER_COOLDOWN", "20")))))
                    HTTP_BREAKER_OPEN_SECONDS.labels(endpoint=ep).set(opened_for)
            if attempt > retries:
                raise err
            if HTTP_RETRIES_TOTAL is not None:
                with suppress(Exception):
                    HTTP_RETRIES_TOTAL.labels(endpoint=ep, reason=type(err).__name__).inc()
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            remaining = (max_cumulative - cumulative_sleep) if max_cumulative else delay
            sleep_for = min(delay, 5, remaining)
            logger.info(
                "retry_sleep",
                endpoint=ep,
                attempt=attempt,
                delay=delay,
                sleep_for=sleep_for,
                cumulative_sleep=cumulative_sleep,
                breaker_state="open",
            )
            await _async_sleep(sleep_for)
            cumulative_sleep += sleep_for
            if RETRY_BUDGET_REMAINING_SECONDS is not None and max_cumulative:
                with suppress(Exception):
                    RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(max(0.0, max_cumulative - cumulative_sleep))
            continue
        try:
            data = await async_http_get_json(client, url, timeout=timeout, headers=headers, params=params)
            return data
        except RETRIABLE_EXC as e:
            if isinstance(e, RateLimitError):
                _record_rate_limit_and_maybe_open(ep, now)
            if attempt > retries:
                raise
            if HTTP_RETRIES_TOTAL is not None:
                with suppress(Exception):
                    HTTP_RETRIES_TOTAL.labels(endpoint=ep, reason=type(e).__name__).inc()
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            remaining = (max_cumulative - cumulative_sleep) if max_cumulative else delay
            if max_cumulative and remaining <= 0:
                logger.warning(
                    "retry_budget_exhausted",
                    endpoint=ep,
                    attempt=attempt,
                    cumulative_sleep=cumulative_sleep,
                    max_cumulative=max_cumulative,
                )
                raise TimeoutError_(
                    f"retry_budget_exhausted {ep} cumulative={cumulative_sleep:.2f}s > {max_cumulative}s"
                ) from e
            sleep_for = min(delay, 5, remaining)
            logger.info(
                "retry_sleep",
                endpoint=ep,
                attempt=attempt,
                delay=delay,
                sleep_for=sleep_for,
                cumulative_sleep=cumulative_sleep,
                breaker_state="closed",
            )
            await _async_sleep(sleep_for)
            cumulative_sleep += sleep_for
            if RETRY_BUDGET_REMAINING_SECONDS is not None and max_cumulative:
                with suppress(Exception):
                    RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(max(0.0, max_cumulative - cumulative_sleep))
            continue


async def _async_sleep(d: float) -> None:  # petite fonction utilitaire locale
    import asyncio

    await asyncio.sleep(min(d, 5))


__all__.append("async_http_get_json_retry")


# ------------------ POST JSON (sync/async) ------------------
def http_post_json(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any | None = None,
    data: Any | None = None,
) -> Any:
    t = timeout or DEFAULT_TIMEOUT
    try:
        r = httpx.post(url, headers=headers, json=json, data=data, timeout=t)
    except httpx.TimeoutException as e:  # pragma: no cover
        raise TimeoutError_(str(e)) from e
    except httpx.RequestError as e:  # pragma: no cover
        raise NetworkError(str(e)) from e
    _map_status(getattr(r, "status_code", 0), url)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:  # pragma: no cover
        raise UpstreamError(str(e)) from e
    try:
        payload = r.json()
    except ValueError as e:
        raise SchemaError(f"invalid_json:{e}") from e
    if payload in (None, {}, []):
        raise EmptyDataError("empty_payload")
    return payload


def http_post_json_retry(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any | None = None,
    data: Any | None = None,
    retries: int = 3,
    backoff_base: float = 0.3,
    classify_endpoint: Callable[[str], str] | None = None,
) -> Any:
    ep = classify_endpoint(url) if classify_endpoint else endpoint_label(url)
    attempt = 0
    cumulative_sleep = 0.0
    max_cumulative = float(os.getenv("RETRY_MAX_CUMULATIVE_SLEEP_SEC", "0"))
    while True:
        attempt += 1
        now = time.time()
        limiter, lim = _get_http_throttle()
        if limiter is not None and lim > 0:
            provider = (ep.split("/")[0]) if "/" in ep else ep
            allowed, wait, _rem, _reset = limiter.check_allow_with_meta(f"http:{provider}")
            if not allowed:
                max_wait = float(os.getenv("HTTP_THROTTLE_MAX_WAIT", "8"))
                sleep_for = min(max(1.0, float(wait)), max_wait)
                logger.info("http_throttle_sleep", endpoint=ep, provider=provider, wait=wait, sleep_for=sleep_for)
                time.sleep(sleep_for)
                cumulative_sleep += sleep_for
                if RETRY_BUDGET_REMAINING_SECONDS is not None and max_cumulative:
                    with suppress(Exception):
                        RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(
                            max(0.0, max_cumulative - cumulative_sleep)
                        )
        if max_cumulative and cumulative_sleep >= max_cumulative:
            if RETRY_BUDGET_EXHAUSTED_TOTAL is not None:
                with suppress(Exception):
                    RETRY_BUDGET_EXHAUSTED_TOTAL.labels(endpoint=ep).inc()
            raise TimeoutError_(f"retry_budget_exhausted {ep} cumulative={cumulative_sleep:.2f}s > {max_cumulative}s")
        if RETRY_BUDGET_REMAINING_SECONDS is not None:
            with suppress(Exception):
                rem = -1 if max_cumulative == 0 else max(0.0, max_cumulative - cumulative_sleep)
                RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(rem)
        if _breaker_should_block(ep, now):
            err = RateLimitError(f"breaker_open {ep}")
            if HTTP_BREAKER_SKIPS_TOTAL is not None:
                with suppress(Exception):
                    HTTP_BREAKER_SKIPS_TOTAL.labels(endpoint=ep).inc()
            until = _BREAKER_OPEN_UNTIL.get(ep)
            if until and HTTP_BREAKER_OPEN_SECONDS is not None:
                with suppress(Exception):
                    opened_for = max(0.0, (time.time() - (until - float(os.getenv("HTTP_BREAKER_COOLDOWN", "20")))))
                    HTTP_BREAKER_OPEN_SECONDS.labels(endpoint=ep).set(opened_for)
            if attempt > retries:
                raise err
            if HTTP_RETRIES_TOTAL is not None:
                with suppress(Exception):
                    HTTP_RETRIES_TOTAL.labels(endpoint=ep, reason=type(err).__name__).inc()
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            remaining = (max_cumulative - cumulative_sleep) if max_cumulative else delay
            sleep_for = min(delay, 5, remaining)
            logger.info(
                "retry_sleep",
                endpoint=ep,
                attempt=attempt,
                delay=delay,
                sleep_for=sleep_for,
                cumulative_sleep=cumulative_sleep,
                breaker_state="open",
            )
            time.sleep(sleep_for)
            cumulative_sleep += sleep_for
            continue
        try:
            return http_post_json(url, timeout=timeout, headers=headers, json=json, data=data)
        except RETRIABLE_EXC as e:
            if isinstance(e, RateLimitError):
                _record_rate_limit_and_maybe_open(ep, now)
            if attempt > retries:
                raise
            if HTTP_RETRIES_TOTAL is not None:
                with suppress(Exception):
                    HTTP_RETRIES_TOTAL.labels(endpoint=ep, reason=type(e).__name__).inc()
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            remaining = (max_cumulative - cumulative_sleep) if max_cumulative else delay
            if max_cumulative and remaining <= 0:
                raise TimeoutError_(
                    f"retry_budget_exhausted {ep} cumulative={cumulative_sleep:.2f}s > {max_cumulative}s"
                ) from e
            sleep_for = min(delay, 5, remaining)
            logger.info("retry_sleep", endpoint=ep, attempt=attempt, delay=delay, sleep_for=sleep_for)
            time.sleep(sleep_for)
            cumulative_sleep += sleep_for
            continue


__all__.extend(["http_post_json", "http_post_json_retry"])


async def async_http_post_json(
    client: AsyncHttpClient,
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any | None = None,
    data: Any | None = None,
) -> Any:
    t = timeout or DEFAULT_TIMEOUT
    try:
        post_kwargs: dict[str, Any] = {"timeout": t}
        if headers is not None:
            post_kwargs["headers"] = headers
        if json is not None:
            post_kwargs["json"] = json
        if data is not None:
            post_kwargs["data"] = data
        r = await client.post(url, **post_kwargs)
    except httpx.TimeoutException as e:  # pragma: no cover
        raise TimeoutError_(str(e)) from e
    except httpx.RequestError as e:  # pragma: no cover
        raise NetworkError(str(e)) from e
    status = getattr(r, "status_code", 200)
    if isinstance(status, int):
        _map_status(status, url)
        try:
            if hasattr(r, "raise_for_status"):
                r.raise_for_status()
        except httpx.HTTPStatusError as e:  # pragma: no cover
            raise UpstreamError(str(e)) from e
    try:
        payload = r.json() if hasattr(r, "json") else getattr(r, "_payload", None)
    except ValueError as e:
        raise SchemaError(f"invalid_json:{e}") from e
    if payload in (None, {}, []):
        raise EmptyDataError("empty_payload")
    return payload


async def async_http_post_json_retry(
    client: AsyncHttpClient,
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any | None = None,
    data: Any | None = None,
    retries: int = 3,
    backoff_base: float = 0.3,
    classify_endpoint: Callable[[str], str] | None = None,
) -> Any:
    ep = classify_endpoint(url) if classify_endpoint else endpoint_label(url)
    attempt = 0
    cumulative_sleep = 0.0
    max_cumulative = float(os.getenv("RETRY_MAX_CUMULATIVE_SLEEP_SEC", "0"))
    while True:
        attempt += 1
        now = time.time()
        limiter, lim = _get_http_throttle()
        if limiter is not None and lim > 0:
            provider = (ep.split("/")[0]) if "/" in ep else ep
            allowed, wait, _rem, _reset = limiter.check_allow_with_meta(f"http:{provider}")
            if not allowed:
                max_wait = float(os.getenv("HTTP_THROTTLE_MAX_WAIT", "8"))
                sleep_for = min(max(1.0, float(wait)), max_wait)
                logger.info("http_throttle_sleep", endpoint=ep, provider=provider, wait=wait, sleep_for=sleep_for)
                await _async_sleep(sleep_for)
                cumulative_sleep += sleep_for
                if RETRY_BUDGET_REMAINING_SECONDS is not None and max_cumulative:
                    with suppress(Exception):
                        RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(
                            max(0.0, max_cumulative - cumulative_sleep)
                        )
        if max_cumulative and cumulative_sleep >= max_cumulative:
            if RETRY_BUDGET_EXHAUSTED_TOTAL is not None:
                with suppress(Exception):
                    RETRY_BUDGET_EXHAUSTED_TOTAL.labels(endpoint=ep).inc()
            raise TimeoutError_(f"retry_budget_exhausted {ep} cumulative={cumulative_sleep:.2f}s > {max_cumulative}s")
        if RETRY_BUDGET_REMAINING_SECONDS is not None:
            with suppress(Exception):
                rem = -1 if max_cumulative == 0 else max(0.0, max_cumulative - cumulative_sleep)
                RETRY_BUDGET_REMAINING_SECONDS.labels(endpoint=ep).set(rem)
        if _breaker_should_block(ep, now):
            err = RateLimitError(f"breaker_open {ep}")
            if HTTP_BREAKER_SKIPS_TOTAL is not None:
                with suppress(Exception):
                    HTTP_BREAKER_SKIPS_TOTAL.labels(endpoint=ep).inc()
            until = _BREAKER_OPEN_UNTIL.get(ep)
            if until and HTTP_BREAKER_OPEN_SECONDS is not None:
                with suppress(Exception):
                    opened_for = max(0.0, (time.time() - (until - float(os.getenv("HTTP_BREAKER_COOLDOWN", "20")))))
                    HTTP_BREAKER_OPEN_SECONDS.labels(endpoint=ep).set(opened_for)
            if attempt > retries:
                raise err
            if HTTP_RETRIES_TOTAL is not None:
                with suppress(Exception):
                    HTTP_RETRIES_TOTAL.labels(endpoint=ep, reason=type(err).__name__).inc()
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            remaining = (max_cumulative - cumulative_sleep) if max_cumulative else delay
            sleep_for = min(delay, 5, remaining)
            logger.info(
                "retry_sleep",
                endpoint=ep,
                attempt=attempt,
                delay=delay,
                sleep_for=sleep_for,
                cumulative_sleep=cumulative_sleep,
                breaker_state="open",
            )
            await _async_sleep(sleep_for)
            cumulative_sleep += sleep_for
            continue
        try:
            return await async_http_post_json(client, url, timeout=timeout, headers=headers, json=json, data=data)
        except RETRIABLE_EXC as e:
            if isinstance(e, RateLimitError):
                _record_rate_limit_and_maybe_open(ep, now)
            if attempt > retries:
                raise
            if HTTP_RETRIES_TOTAL is not None:
                with suppress(Exception):
                    HTTP_RETRIES_TOTAL.labels(endpoint=ep, reason=type(e).__name__).inc()
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            remaining = (max_cumulative - cumulative_sleep) if max_cumulative else delay
            if max_cumulative and remaining <= 0:
                raise TimeoutError_(
                    f"retry_budget_exhausted {ep} cumulative={cumulative_sleep:.2f}s > {max_cumulative}s"
                ) from e
            sleep_for = min(delay, 5, remaining)
            logger.info("retry_sleep", endpoint=ep, attempt=attempt, delay=delay, sleep_for=sleep_for)
            await _async_sleep(sleep_for)
            cumulative_sleep += sleep_for
            continue


__all__.extend(["async_http_post_json", "async_http_post_json_retry"])


# ------------------ TEXT GET (sync/async) ------------------
def http_get_text(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
) -> str:
    t = timeout or DEFAULT_TIMEOUT
    try:
        r = httpx.get(url, headers=headers, params=params, timeout=t)
    except httpx.TimeoutException as e:  # pragma: no cover
        raise TimeoutError_(str(e)) from e
    except httpx.RequestError as e:  # pragma: no cover
        raise NetworkError(str(e)) from e
    _map_status(getattr(r, "status_code", 0), url)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:  # pragma: no cover
        raise UpstreamError(str(e)) from e
    txt = cast(str, getattr(r, "text", ""))
    if txt is None or txt == "":
        raise EmptyDataError("empty_payload")
    return txt


async def async_http_get_text(
    client: AsyncHttpClient,
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
) -> str:
    t = timeout or DEFAULT_TIMEOUT
    try:
        kwargs: dict[str, Any] = {"timeout": t}
        if headers is not None:
            kwargs["headers"] = headers
        if params is not None:
            kwargs["params"] = params
        r = await client.get(url, **kwargs)
    except httpx.TimeoutException as e:  # pragma: no cover
        raise TimeoutError_(str(e)) from e
    except httpx.RequestError as e:  # pragma: no cover
        raise NetworkError(str(e)) from e
    status = getattr(r, "status_code", 200)
    if isinstance(status, int):
        _map_status(status, url)
        try:
            if hasattr(r, "raise_for_status"):
                r.raise_for_status()
        except httpx.HTTPStatusError as e:  # pragma: no cover
            raise UpstreamError(str(e)) from e
    txt = cast(str, getattr(r, "text", ""))
    if txt is None or txt == "":
        raise EmptyDataError("empty_payload")
    return txt


def http_get_text_retry(
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    retries: int = 3,
    backoff_base: float = 0.3,
    classify_endpoint: Callable[[str], str] | None = None,
) -> str:
    ep = classify_endpoint(url) if classify_endpoint else endpoint_label(url)
    attempt = 0
    while True:
        attempt += 1
        now = time.time()
        if _breaker_should_block(ep, now):
            err = RateLimitError(f"breaker_open {ep}")
            if attempt > retries:
                raise err
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            sleep_for = min(delay, 5, delay)
            time.sleep(sleep_for)
            continue
        try:
            return http_get_text(url, timeout=timeout, headers=headers, params=params)
        except RETRIABLE_EXC:
            if attempt > retries:
                raise
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            time.sleep(min(delay, 5, delay))
            continue


async def async_http_get_text_retry(
    client: AsyncHttpClient,
    url: str,
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    retries: int = 3,
    backoff_base: float = 0.3,
    classify_endpoint: Callable[[str], str] | None = None,
) -> str:
    ep = classify_endpoint(url) if classify_endpoint else endpoint_label(url)
    attempt = 0
    max_cumulative = float(os.getenv("RETRY_MAX_CUMULATIVE_SLEEP_SEC", "0"))
    cumul = 0.0
    while True:
        attempt += 1
        now = time.time()
        if _breaker_should_block(ep, now):
            err = RateLimitError(f"breaker_open {ep}")
            if attempt > retries:
                raise err
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            sleep_for = min(delay, 5, delay)
            await _async_sleep(sleep_for)
            cumul += sleep_for
            continue
        try:
            return await async_http_get_text(client, url, timeout=timeout, headers=headers, params=params)
        except RETRIABLE_EXC as e:
            if attempt > retries:
                raise
            delay = backoff_base * (2 ** (attempt - 1)) * random.uniform(0.8, 1.3)
            sleep_for = min(delay, 5, delay)
            await _async_sleep(sleep_for)
            cumul += sleep_for
            if max_cumulative and cumul >= max_cumulative:
                raise TimeoutError_(f"retry_budget_exhausted {ep} cumulative={cumul:.2f}s > {max_cumulative}s") from e
            continue


__all__.extend(
    [
        "http_get_text",
        "http_get_text_retry",
        "async_http_get_text",
        "async_http_get_text_retry",
    ]
)

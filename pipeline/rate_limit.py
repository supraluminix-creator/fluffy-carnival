from __future__ import annotations

import importlib
import math
import os
from collections import deque
from threading import Lock
from time import time
from typing import Any, Protocol

try:
    redis: Any = importlib.import_module("redis")
except Exception:  # pragma: no cover - module optionnel
    redis = None


class RateLimiter:
    def __init__(self, limit_per_minute: int = 60) -> None:
        self.limit = max(1, int(limit_per_minute))
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _now(self) -> float:  # for tests monkeypatching
        return time()

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def check_allow(self, key: str) -> bool:
        now = self._now()
        window_start = now - 60.0
        with self._lock:
            dq = self._buckets.get(key)
            if dq is None:
                dq = deque()
                self._buckets[key] = dq
            # purge
            while dq and dq[0] < window_start:
                dq.popleft()
            if len(dq) >= self.limit:
                return False
            dq.append(now)
            return True

    def check_allow_with_retry_after(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds).

        retry_after_seconds is 0 if allowed, otherwise number of seconds to wait before next token is available.
        """
        now = self._now()
        window_start = now - 60.0
        with self._lock:
            dq = self._buckets.get(key)
            if dq is None:
                dq = deque()
                self._buckets[key] = dq
            while dq and dq[0] < window_start:
                dq.popleft()
            if len(dq) >= self.limit:
                # next available when oldest expires
                oldest = dq[0]
                wait = max(1, int(math.ceil((oldest + 60.0) - now)))
                return False, wait
            dq.append(now)
            return True, 0

    def check_allow_with_meta(self, key: str) -> tuple[bool, int, int, int]:
        """Return (allowed, retry_after_seconds, remaining_after, reset_after_seconds).

        remaining_after is the number of requests remaining in the current 60s window AFTER
        accounting for this request when allowed. When not allowed, remaining_after is 0.

        reset_after_seconds is the number of seconds until the current rolling window resets
        (i.e., until the oldest kept request timestamp expires). If there is no prior request,
        it will be close to 60 seconds after the first allowed request.
        """
        now = self._now()
        window_start = now - 60.0
        with self._lock:
            dq = self._buckets.get(key)
            if dq is None:
                dq = deque()
                self._buckets[key] = dq
            while dq and dq[0] < window_start:
                dq.popleft()
            if len(dq) >= self.limit:
                oldest = dq[0]
                wait = max(1, int(math.ceil((oldest + 60.0) - now)))
                return False, wait, 0, wait
            # allow and compute remaining after append
            dq.append(now)
            remaining = max(0, self.limit - len(dq))
            oldest = dq[0]
            reset_after = max(1, int(math.ceil((oldest + 60.0) - now)))
            return True, 0, remaining, reset_after


class SupportsRedisClient(Protocol):
    def pipeline(self) -> Any: ...
    def ping(self) -> Any: ...
    # from_url is module-level, not on client instance


class RedisRateLimiter:
    """Rate limiter basé sur Redis (fenêtre fixe par minute). Optionnel.

    Implémentation simple par incrément sur clé de la forme rl:{key}:{epoch_min} avec expire 70s.
    Diffère légèrement du sliding window en mémoire mais acceptable pour une version initiale.
    """

    def __init__(self, client: SupportsRedisClient, limit_per_minute: int = 60, prefix: str = "rl") -> None:
        self.limit = max(1, int(limit_per_minute))
        self.client = client
        self.prefix = prefix

    def _now(self) -> float:  # align avec in-memory pour tests
        return time()

    def _bucket_key(self, key: str, epoch_min: int) -> str:
        return f"{self.prefix}:{key}:{epoch_min}"

    def reset(self) -> None:
        # Reset global non supporté efficacement côté Redis sans scan; no-op.
        pass

    def check_allow_with_meta(self, key: str) -> tuple[bool, int, int, int]:
        now = self._now()
        # minute courante
        epoch_min = int(now // 60)
        rkey = self._bucket_key(key, epoch_min)
        # incrémenter et fixer une expiration si première fois
        # NOTE: utiliser pipeline pour set expire à la première incr.
        pipe = self.client.pipeline()
        pipe.incr(rkey)
        pipe.expire(rkey, 70)
        try:
            cnt, _ = pipe.execute()
        except Exception:
            # En cas d'erreur Redis, fail-safe: autoriser (éviter de casser le flux)
            return True, 0, max(0, self.limit - 1), max(1, 60 - int(now) % 60)

        count = int(cnt or 0)
        if count > self.limit:
            # Retry after: jusqu'au prochain début de minute
            secs_into_min = int(now) % 60
            retry_after = max(1, 60 - secs_into_min)
            return False, retry_after, 0, retry_after
        remaining = max(0, self.limit - count)
        # Reset après: temps jusqu'à prochaine minute
        secs_into_min = int(now) % 60
        reset_after = max(1, 60 - secs_into_min)
        return True, 0, remaining, reset_after


def build_rate_limiter_from_env(limit_per_minute: int = 60) -> RateLimiter | RedisRateLimiter:
    """Construit un rate limiter en fonction des variables d'env.

    Si API_RATE_LIMIT_BACKEND=redis et que le module redis est disponible ainsi qu'une URL, utilise Redis.
    Sinon, retourne RateLimiter (in-memory sliding window).
    """
    backend = (os.getenv("API_RATE_LIMIT_BACKEND") or "").strip().lower()
    if backend == "redis":
        if redis is None:
            return RateLimiter(limit_per_minute)
        url = os.getenv("REDIS_URL") or os.getenv("API_REDIS_URL")
        if not url:
            return RateLimiter(limit_per_minute)
        try:
            # from_url est présent sur le module redis
            client = redis.from_url(url, decode_responses=True)
            # ping léger pour valider la connexion
            try:
                client.ping()
            except Exception:
                # si ping échoue, fallback
                return RateLimiter(limit_per_minute)
            return RedisRateLimiter(client, limit_per_minute)
        except Exception:
            return RateLimiter(limit_per_minute)
    # défaut: in-memory
    return RateLimiter(limit_per_minute)

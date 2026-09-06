from __future__ import annotations

from pipeline.rate_limit import RedisRateLimiter


class FakePipe:
    def __init__(self, store: dict, key: str):
        self.store = store
        self.key = key
        self.ops: list[tuple[object, ...]] = []

    def incr(self, k):
        self.ops.append(("incr", k))
        return self

    def expire(self, k, ttl):
        self.ops.append(("expire", k, ttl))
        return self

    def execute(self):
        # executor très simple
        cnt = self.store.get(self.key, 0) + 1
        self.store[self.key] = cnt
        return [cnt, True]


class FakeRedis:
    def __init__(self):
        self.store = {}
        self._ok = True

    def pipeline(self):
        # la clé exacte sera fournie par le limiter; on ignore ici et laissons RedisRateLimiter construire la clé
        # on renvoie un pipeline qui écrit dans store avec clé passée à execute
        # pour simplifier, on se base sur l'état défini dans le limiter
        return FakePipe(self.store, getattr(self, "__last_key", "unknown"))

    def set_last_key(self, key: str):
        self.__last_key = key

    def ping(self):
        if not self._ok:
            raise RuntimeError("down")


def test_redis_rate_limiter_basic(monkeypatch):
    fr = FakeRedis()
    rl = RedisRateLimiter(fr, limit_per_minute=2, prefix="t")

    # monkeypatch _bucket_key pour que FakeRedis sache où écrire
    def _bk(key: str, epoch_min: int):
        k = f"t:{key}:{epoch_min}"
        fr.set_last_key(k)
        return k

    rl._bucket_key = _bk  # type: ignore

    ok1 = rl.check_allow_with_meta("a")
    assert ok1[0] is True and ok1[2] == 1
    ok2 = rl.check_allow_with_meta("a")
    assert ok2[0] is True and ok2[2] == 0
    no = rl.check_allow_with_meta("a")
    assert no[0] is False and no[2] == 0


def test_factory_fallbacks(monkeypatch):
    # Pas de backend redis -> in-memory
    monkeypatch.delenv("API_RATE_LIMIT_BACKEND", raising=False)
    from pipeline import rate_limit as rlmod

    rl = rlmod.build_rate_limiter_from_env(5)
    assert rl.__class__.__name__ == "RateLimiter"

    # Forcer redis mais sans URL -> fallback
    monkeypatch.setenv("API_RATE_LIMIT_BACKEND", "redis")
    monkeypatch.delenv("REDIS_URL", raising=False)
    rl2 = rlmod.build_rate_limiter_from_env(5)
    assert rl2.__class__.__name__ == "RateLimiter"

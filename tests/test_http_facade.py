import os
import types
import pytest

from pipeline.http import fetch_json, async_fetch_json
from pipeline import http_wrappers
from pipeline.metrics import HTTP_RETRIES_TOTAL

class DummyResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload
    def raise_for_status(self):
        pass

@pytest.mark.parametrize("mode", ["sync", "async"])
def test_http_facade_retry(monkeypatch, mode):
    monkeypatch.setenv("RETRY_HTTP_ENABLED", "1")
    monkeypatch.setenv("RETRY_HTTP_MAX", "2")  # 2 retries -> 3 tentatives total
    monkeypatch.setenv("HTTP_BREAKER_THRESHOLD", "99")  # éviter ouverture breaker durant test
    monkeypatch.setenv("HTTP_BREAKER_COOLDOWN", "1")
    # Purge état breaker / rate limit pour éviter contamination entre paramétrisations
    try:
        http_wrappers._RATE_LIMIT_EVENTS.clear()  # type: ignore[attr-defined]
        http_wrappers._BREAKER_OPEN_UNTIL.clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    calls = {"n":0}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:  # deux premières: 429
            class R:
                status_code = 429
                def json(self):
                    return {"error":"rate"}
                def raise_for_status(self):
                    pass
            return R()
        return DummyResp(200, {"ok": True})

    monkeypatch.setattr(http_wrappers.httpx, "get", fake_get)

    async def fake_async_get(self, url, **kwargs):  # self = AsyncClient instance
        # Reutilise la logique compteur pour aligner comportement
        calls["n"] += 1
        if calls["n"] < 3:
            class AR:
                status_code = 429
                def json(self):
                    return {"error":"rate"}
                def raise_for_status(self):
                    pass
            return AR()
        return DummyResp(200, {"ok": True})

    monkeypatch.setattr(http_wrappers.httpx.AsyncClient, "get", fake_async_get, raising=True)

    if mode == "sync":
        # baseline valeur avant exécution
        baseline = HTTP_RETRIES_TOTAL.labels(endpoint="llama/chains", reason="RateLimitError")._value.get()
        data = fetch_json("https://api.llama.fi/chains")
        assert data["ok"] is True
    else:
        import asyncio
        async def run():
            return await async_fetch_json("https://api.llama.fi/chains")
        baseline = HTTP_RETRIES_TOTAL.labels(endpoint="llama/chains", reason="RateLimitError")._value.get()
        data = asyncio.run(run())
        assert data["ok"] is True

    # Deux retries enregistrés
    val = HTTP_RETRIES_TOTAL.labels(endpoint="llama/chains", reason="RateLimitError")._value.get()
    assert (val - baseline) == 2
    assert calls["n"] == 3

from typing import Any

import httpx
import pytest

from pipeline.collectors import derivatives as deriv_mod


class DummyResp:
    def __init__(self, payload: Any, raise_error: Exception | None = None):
        self._payload = payload
        self._err = raise_error

    def raise_for_status(self):  # pragma: no cover - trivial
        if self._err:
            raise self._err

    def json(self):
        return self._payload


class DummyAsyncClient:
    def __init__(self, responses: list[Any]):
        self._responses = list(responses)

    async def __aenter__(self):  # pragma: no cover
        return self

    async def __aexit__(self, exc_type, exc, tb):  # pragma: no cover
        return False

    async def get(self, url: str, params: dict[str, Any] | None = None, timeout: int = 10):  # noqa: D401
        if not self._responses:
            raise RuntimeError("No more responses configured")
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


@pytest.mark.asyncio
async def test_derivatives_fallback_double_failure(monkeypatch):
    # Bybit path raises, then Binance path raises -> return None
    def factory(*a, **k):
        return DummyAsyncClient(
            [
                Exception("bybit fail"),
                Exception("binance fail"),
            ]
        )

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    res = await deriv_mod.fetch_bybit_oi("XFAILUSDT", cache_ttl=1)
    assert res is None


@pytest.mark.asyncio
async def test_derivatives_lsr_cache_hit(monkeypatch):
    # Reset breaker state to avoid contamination from previous tests
    from pipeline import circuit_breaker

    circuit_breaker.reset()
    # First call returns data, second call should hit cache and not invoke client again
    lsr_payload = {"result": {"list": [{"timestamp": 1700, "buyRatio": "0.6", "sellRatio": "0.4"}]}}
    calls: list[str] = []

    class OneShotClient(DummyAsyncClient):
        async def get(self, url: str, params: dict[str, Any] | None = None, timeout: int = 10):
            calls.append(url)
            return await super().get(url, params=params, timeout=timeout)

    def factory(*a, **k):
        return OneShotClient([DummyResp(lsr_payload)])

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    # First call populates cache
    first = await deriv_mod.fetch_bybit_long_short_ratio("CACHECOIN", cache_ttl=30)
    assert first is not None
    # Second call uses cache (no extra http call)
    second = await deriv_mod.fetch_bybit_long_short_ratio("CACHECOIN", cache_ttl=30)
    assert second is not None
    assert len(calls) == 1

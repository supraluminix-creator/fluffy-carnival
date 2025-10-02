from typing import Any

import httpx
import pytest

from pipeline.collectors import market as market_mod


class DummyResp:
    def __init__(self, payload: Any, raise_error: Exception | None = None):
        self._payload = payload
        self._err = raise_error

    def raise_for_status(self):  # pragma: no cover - trivial
        if self._err:
            raise self._err

    def json(self):
        return self._payload


def test_fetch_market_double_failure(monkeypatch):
    # Primary + fallback both fail -> None
    def fake_get(url: str, timeout: int = 10):  # noqa: D401
        raise RuntimeError("boom")

    monkeypatch.setattr(httpx, "get", fake_get)
    res = market_mod.fetch_market("failcoin")
    assert res is None


def test_fetch_market_cache_hit(monkeypatch):
    payload = {
        "market_data": {
            "current_price": {"usd": 1.0},
            "total_volume": {"usd": 2},
            "market_cap": {"usd": 3},
            "market_cap_rank": 4,
        }
    }

    calls: list[str] = []

    def fake_get(url: str, timeout: int = 10):  # noqa: D401
        calls.append(url)
        return DummyResp(payload)

    monkeypatch.setattr(httpx, "get", fake_get)
    rec1 = market_mod.fetch_market("cachecoin1")
    rec2 = market_mod.fetch_market("cachecoin1")  # cache hit
    assert rec1 is not None and rec2 is not None
    assert len(calls) == 1


class DummyAsyncClient:
    def __init__(self, responses: list[Any]):
        self._responses = list(responses)

    async def __aenter__(self):  # pragma: no cover - trivial
        return self

    async def __aexit__(self, exc_type, exc, tb):  # pragma: no cover - trivial
        return False

    async def get(self, url: str, headers: dict[str, str] | None = None, timeout: int = 10):
        if not self._responses:
            raise RuntimeError("no more responses")
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


@pytest.mark.asyncio
async def test_fetch_macro_fallback_error(monkeypatch):
    # Primary fails, fallback also fails -> None
    symbol = "macrofail1"

    def factory(*a, **k):
        return DummyAsyncClient([
            Exception("cg fail"),
            Exception("cmc fail"),
        ])

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    res = await market_mod.fetch_macro(symbol, cmc_api_key="X", cache_ttl=1)
    assert res is None


@pytest.mark.asyncio
async def test_fetch_macro_cache_hit(monkeypatch):
    symbol = "macrocache1"
    payload = {
        "last_updated": "2025-09-20T00:00:00Z",
        "market_data": {
            "current_price": {"usd": 10.0},
            "total_volume": {"usd": 20.0},
            "market_cap": {"usd": 30.0},
            "market_cap_rank": 1,
        },
    }

    calls: list[str] = []

    class OneShot(DummyAsyncClient):
        async def get(self, url: str, headers: dict[str, str] | None = None, timeout: int = 10):
            calls.append(url)
            return await super().get(url, headers=headers, timeout=timeout)

    def factory(*a, **k):
        return OneShot([DummyResp(payload)])

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    first = await market_mod.fetch_macro(symbol, cache_ttl=5)
    second = await market_mod.fetch_macro(symbol, cache_ttl=5)
    assert first is not None and second is not None
    assert len(calls) == 1

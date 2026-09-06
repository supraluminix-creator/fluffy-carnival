from typing import Any

import httpx
import pytest

from pipeline import circuit_breaker
from pipeline.collectors.derivatives import (
    fetch_bybit_long_short_ratio,
    fetch_bybit_oi,
)


class DummyResp:
    def __init__(self, payload: Any):
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover
        return

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_derivatives_oi_bybit_success(monkeypatch):
    circuit_breaker.reset()  # ensure clean state
    payload: dict[str, object] = {"result": {"list": [{"timestamp": 1700000000000, "openInterest": "1234.56"}]}}

    class DummyAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, params: dict[str, Any] | None = None, timeout: int = 10):  # noqa: D401
            return DummyResp(payload)

    monkeypatch.setattr(httpx, "AsyncClient", DummyAsyncClient)
    rec = await fetch_bybit_oi("BTCUSDT", cache_ttl=1)
    assert rec is not None
    assert rec["metric_name"] == "open_interest"
    assert rec["source"] == "bybit"
    assert isinstance(rec["value"], float) and rec["value"] > 0


@pytest.mark.asyncio
async def test_derivatives_oi_binance_fallback(monkeypatch):
    circuit_breaker.reset()
    # First call (Bybit) returns empty list to trigger fallback, second call (Binance) returns data list.
    bybit_payload: dict[str, object] = {"result": {"list": []}}
    binance_payload: list[dict[str, object]] = [{"timestamp": 1700000005000, "sumOpenInterest": "999.9"}]
    calls: list[str] = []

    class DummyAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, params: dict[str, Any] | None = None, timeout: int = 10):  # noqa: D401
            calls.append(url)
            if "bybit" in url:
                return DummyResp(bybit_payload)
            return DummyResp(binance_payload)

    monkeypatch.setattr(httpx, "AsyncClient", DummyAsyncClient)
    rec = await fetch_bybit_oi("ETHUSDT", cache_ttl=1)
    assert rec is not None
    assert rec["source"] == "binance"
    assert rec["metric_name"] == "open_interest"
    assert len(calls) == 2  # bybit then binance


@pytest.mark.asyncio
async def test_derivatives_long_short_ratio_success(monkeypatch):
    circuit_breaker.reset()
    payload: dict[str, object] = {
        "result": {"list": [{"timestamp": 1700000010000, "buyRatio": "0.55", "sellRatio": "0.45"}]}
    }

    class DummyAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, params: dict[str, Any] | None = None, timeout: int = 10):
            return DummyResp(payload)

    monkeypatch.setattr(httpx, "AsyncClient", DummyAsyncClient)
    rec = await fetch_bybit_long_short_ratio("BTCUSDT", cache_ttl=1)
    assert rec is not None
    assert rec["metric_name"] == "long_short_ratio"
    assert rec["source"] == "bybit"
    assert isinstance(rec["value"]["buy_ratio"], float)
    assert isinstance(rec["value"]["sell_ratio"], float)


@pytest.mark.asyncio
async def test_derivatives_long_short_ratio_failure(monkeypatch):
    circuit_breaker.reset()
    payload: dict[str, object] = {"result": {"list": []}}  # triggers error path

    class DummyAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, params: dict[str, Any] | None = None, timeout: int = 10):
            return DummyResp(payload)

    monkeypatch.setattr(httpx, "AsyncClient", DummyAsyncClient)
    rec = await fetch_bybit_long_short_ratio("BTCUSDT", cache_ttl=1)
    assert rec is None

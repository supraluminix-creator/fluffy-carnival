import os

import httpx
import pytest

from pipeline.collectors.derivatives import fetch_bybit_funding, fetch_bybit_oi


class DummyResp:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code != 200:
            raise httpx.HTTPStatusError("err", request=None, response=None)


@pytest.mark.asyncio
async def test_deriv_oi_third_fallback_function(monkeypatch):
    # Reset circuit breaker to avoid unintended open state
    try:
        from pipeline.circuit_breaker import reset as breaker_reset

        breaker_reset("deriv_oi")
    except Exception:
        pass

    # Force Bybit failure
    async def fake_async_get(*args, **kwargs):
        raise RuntimeError("bybit down")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_async_get)

    # Force Binance hist empty to push to third fallback
    def fake_httpx_get(url, params=None, timeout=10):
        return DummyResp({"data": []})  # empties list triggers error path

    monkeypatch.setattr(httpx, "get", fake_httpx_get)

    # Enable function fallback
    os.environ["ENABLE_BINANCE_OI_FALLBACK"] = "1"

    # Provide fake function fallback
    def fake_func(sym):
        return {
            "timestamp": 1234567890,
            "symbol": sym,
            "metric_name": "open_interest",
            "value": 42.0,
            "currency": "USD",
            "source": "binance_function",
            "confidence_score": 0.6,
        }

    monkeypatch.setattr("pipeline.collectors.derivatives.fetch_binance_futures_oi", fake_func)

    rec = await fetch_bybit_oi("BTCUSDT")
    assert rec is not None
    assert rec["source"] == "binance_function"
    assert rec["value"] == 42.0


@pytest.mark.asyncio
async def test_deriv_oi_empty_binance_hist_error(monkeypatch):
    try:
        from pipeline.circuit_breaker import reset as breaker_reset

        breaker_reset("deriv_oi")
    except Exception:
        pass

    # Bybit failure
    async def fail_bybit(*args, **kwargs):
        raise RuntimeError("bybit fail")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_bybit)

    # Binance hist returns empty (no third fallback flag)
    def fake_httpx_get(url, params=None, timeout=10):
        return DummyResp({"data": []})

    monkeypatch.setattr(httpx, "get", fake_httpx_get)

    if "ENABLE_BINANCE_OI_FALLBACK" in os.environ:
        del os.environ["ENABLE_BINANCE_OI_FALLBACK"]

    rec = await fetch_bybit_oi("BTCUSDT")
    assert rec is None  # error branch hits, chain stops without third fallback


@pytest.mark.asyncio
async def test_deriv_funding_primary_fail_fallback_success(monkeypatch):
    try:
        from pipeline.circuit_breaker import reset as breaker_reset

        breaker_reset("deriv_funding")
    except Exception:
        pass

    # Primary Bybit funding fails
    async def fail_funding(self, url, params=None, timeout=10):
        raise RuntimeError("funding primary fail")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_funding)

    # Provide binance funding fallback function import patch
    def fake_binance_funding(symbol):
        return {
            "timestamp": 111111,
            "symbol": symbol,
            "metric_name": "funding_rate",
            "value": 0.001,
            "source": "binance",
            "confidence_score": 0.8,
        }

    monkeypatch.setattr("pipeline.collectors.derivatives.fetch_binance_funding", fake_binance_funding)

    rec = await fetch_bybit_funding("BTCUSDT")
    assert rec is not None
    assert rec["source"] == "binance"
    assert rec["value"] == 0.001


@pytest.mark.asyncio
async def test_deriv_funding_primary_and_fallback_fail(monkeypatch):
    try:
        from pipeline.circuit_breaker import reset as breaker_reset

        breaker_reset("deriv_funding")
    except Exception:
        pass

    # Primary fails
    async def fail_primary(self, url, params=None, timeout=10):
        raise RuntimeError("primary funding down")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_primary)

    # Fallback also fails
    def failing_binance(symbol):
        raise RuntimeError("binance funding fail")

    monkeypatch.setattr("pipeline.collectors.derivatives.fetch_binance_funding", failing_binance)

    rec = await fetch_bybit_funding("BTCUSDT")
    assert rec is None

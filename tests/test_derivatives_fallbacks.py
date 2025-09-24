import os
import pytest
from pipeline.collectors import derivatives as deriv_mod


@pytest.mark.asyncio
async def test_oi_fallback_binance(monkeypatch):
    calls = {"bybit": 0, "binance": 0}

    async def fail_bybit(*a, **k):  # simulate bybit failure
        calls["bybit"] += 1
        raise RuntimeError("bybit_down")

    def fake_binance(symbol):
        calls["binance"] += 1
        return {
            "timestamp": 1,
            "symbol": symbol,
            "metric_name": "open_interest",
            "value": 1234.56,
            "source": "binance_futures",
            "confidence_score": 0.85,
        }

    monkeypatch.setenv("ENABLE_BINANCE_OI_FALLBACK", "1")
    monkeypatch.setattr(deriv_mod, "should_skip", lambda *a, **k: False)
    monkeypatch.setattr(deriv_mod.httpx, "AsyncClient", lambda: _DummyAsyncClientError())
    # détourner la fonction interne en provoquant l'exception sur bloc principal => on force except
    monkeypatch.setattr(deriv_mod, "fetch_binance_futures_oi", fake_binance)

    res = await deriv_mod.fetch_bybit_oi("BTCUSDT")
    assert res is not None
    assert res["source"] == "binance_futures"


class _DummyAsyncClientError:
    """Contexte async qui lève sur get pour simuler échec Bybit."""
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    async def get(self, *a, **k):  # always fail
        raise RuntimeError("network_down")


@pytest.mark.asyncio
async def test_funding_fallback_binance(monkeypatch):
    calls = {"bybit": 0, "binance": 0}

    class _DummyClientFunding:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def get(self, *a, **k):
            calls["bybit"] += 1
            raise RuntimeError("bybit_down")

    def fake_binance(symbol):
        calls["binance"] += 1
        return {
            "timestamp": 1,
            "asset": symbol[:-4],
            "symbol": symbol,
            "metric_name": "funding_rate",
            "value": 0.0001,
            "source": "binance_futures",
            "confidence_score": 0.8,
        }

    monkeypatch.setenv("ENABLE_BINANCE_FUNDING_FALLBACK", "1")
    monkeypatch.setattr(deriv_mod, "should_skip", lambda *a, **k: False)
    monkeypatch.setattr(deriv_mod.httpx, "AsyncClient", lambda: _DummyClientFunding())
    monkeypatch.setattr(deriv_mod, "fetch_binance_funding", fake_binance)

    res = await deriv_mod.fetch_bybit_funding("BTCUSDT")
    assert res is not None
    assert res["source"] == "binance_futures"
import os
import pytest
from pipeline.collectors import market as market_mod


@pytest.mark.asyncio
async def test_macro_fallback_binance_then_none(monkeypatch):
    """CoinGecko échoue, Binance (flag activé) réussit."""
    calls = {"coingecko": 0, "binance": 0}

    async def fake_async_get(session, url, timeout):  # CoinGecko simulation
        calls["coingecko"] += 1
        raise RuntimeError("cg_down")

    def fake_binance(symbol):
        calls["binance"] += 1
        return {
            "timestamp": 1,
            "asset": "BTC",
            "symbol": "BTCUSDT",
            "metric_name": "spot_price_usdt",
            "value": 42000.0,
            "source": "binance_spot",
            "confidence_score": 0.9,
        }

    monkeypatch.setenv("ENABLE_BINANCE_SPOT_FALLBACK", "1")
    monkeypatch.setenv("ENABLE_BINANCE_MACRO_FALLBACK", "0")
    monkeypatch.setattr(market_mod, "_async_http_get_json", fake_async_get)
    monkeypatch.setattr(market_mod, "fetch_binance_spot_price", fake_binance)

    res = await market_mod.fetch_macro("bitcoin")
    assert res is not None
    assert res["source"] == "binance_spot"
    assert calls["coingecko"] == 1
    assert calls["binance"] == 1


@pytest.mark.asyncio
async def test_macro_fallback_cmc_after_binance_fail(monkeypatch):
    """CoinGecko échoue, Binance échoue, CMC réussit (on simule)."""
    calls = {"coingecko": 0, "binance": 0, "cmc": 0}

    async def fake_async_get(session, url, timeout):  # CoinGecko fail
        calls["coingecko"] += 1
        raise RuntimeError("cg_down")

    def fake_binance(symbol):
        calls["binance"] += 1
        return None

    # Monkeypatch httpx.get utilisé dans la branche CMC
    import httpx

    def fake_httpx_get(url, *args, **kwargs):
        class R:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                calls["cmc"] += 1
                return {"data": {"BTC": {"quote": {"USD": {"price": 43000.0}}}}}
        return R()

    monkeypatch.setenv("ENABLE_BINANCE_SPOT_FALLBACK", "1")
    monkeypatch.setenv("ENABLE_BINANCE_MACRO_FALLBACK", "0")
    monkeypatch.setattr(market_mod, "_async_http_get_json", fake_async_get)
    monkeypatch.setattr(market_mod, "fetch_binance_spot_price", fake_binance)
    monkeypatch.setattr(httpx, "get", fake_httpx_get)

    res = await market_mod.fetch_macro("bitcoin")
    assert res is not None
    assert calls == {"coingecko": 1, "binance": 1, "cmc": 1}
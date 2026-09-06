import pytest

from pipeline.collectors import market as market_module


@pytest.mark.asyncio
async def test_macro_no_flag_keeps_original(monkeypatch):
    # S'assure que sans flag on ne tente pas la seconde fallback (simuler échec première source + coingecko)
    calls = {
        "binance": 0,
        "coingecko": 0,
    }

    async def fake_http_get(_session, url, *, timeout=10, headers=None, **_kwargs):
        _ = (timeout, headers, _kwargs)
        if "macro.source1" in url:
            raise RuntimeError("primary down")
        if "coingecko" in url:
            calls["coingecko"] += 1
            raise RuntimeError("coingecko down")
        if "binance" in url:
            calls["binance"] += 1
            return {"price": 123}
        raise RuntimeError("unexpected url")

    monkeypatch.setenv("ENABLE_BINANCE_MACRO_FALLBACK", "0")
    monkeypatch.setattr(market_module, "_async_http_get_json", fake_http_get)

    res = await market_module.fetch_macro()
    # Sans flag, après deux échecs on doit retourner None (pas d'appel binance)
    assert res is None
    assert calls["coingecko"] == 1
    assert calls["binance"] == 0


@pytest.mark.asyncio
async def test_macro_with_flag_triggers_binance(monkeypatch):
    calls = {
        "binance": 0,
        "coingecko": 0,
    }

    async def fake_http_get(_session, url, *, timeout=10, headers=None, **_kwargs):
        _ = (timeout, headers, _kwargs)
        if "macro.source1" in url:
            raise RuntimeError("primary down")
        if "coingecko" in url:
            calls["coingecko"] += 1
            raise RuntimeError("coingecko down")
        if "binance" in url:
            calls["binance"] += 1
            return {"price": 123.45}
        raise RuntimeError("unexpected url")

    monkeypatch.setenv("ENABLE_BINANCE_MACRO_FALLBACK", "1")
    monkeypatch.setattr(market_module, "_async_http_get_json", fake_http_get)

    res = await market_module.fetch_macro()
    assert res == {"macro_price_usd": 123.45}
    assert calls["coingecko"] == 1
    assert calls["binance"] == 1

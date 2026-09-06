import pytest
from prometheus_client import REGISTRY

from pipeline.collectors import market as market_mod


def _get_depth(collector: str):
    for metric in REGISTRY.collect():  # brute-force search; acceptable test scope
        if metric.name == "fallback_chain_depth":
            for s in metric.samples:
                if s.labels.get("collector") == collector:
                    return s.value
    return None


@pytest.mark.asyncio
async def test_fallback_chain_depth_macro(monkeypatch):
    # Force CoinGecko failure -> Binance success
    async def fail_coingecko(session, url, **kwargs):
        raise RuntimeError("cg_down")

    def fake_binance(symbol):
        return {
            "timestamp": 1,
            "asset": "BTC",
            "symbol": symbol,
            "metric_name": "spot_price_usdt",
            "value": 40000.0,
            "source": "binance_spot",
            "confidence_score": 0.9,
        }

    monkeypatch.setenv("ENABLE_BINANCE_SPOT_FALLBACK", "1")
    monkeypatch.setattr(market_mod, "fetch_binance_spot_price", fake_binance)
    monkeypatch.setattr(market_mod, "_async_http_get_json", fail_coingecko, raising=True)

    res = await market_mod.fetch_macro("bitcoin")
    assert res is not None and res["source"] == "binance_spot"
    depth = _get_depth("macro")
    assert depth in (2, 3)  # selon ordre d'initialisation possible (2 attendu)

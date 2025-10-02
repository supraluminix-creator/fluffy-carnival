import httpx
import pytest

from pipeline.collectors import defillama as defillama_mod
from pipeline.collectors import market as market_mod


@pytest.mark.asyncio
async def test_defillama_cache_metrics(monkeypatch):
    async def fake_chain(chain: str):
        return {"name": chain, "tvl": 100}
    async def fake_hist(chain: str):
        return [[1, 50]]
    monkeypatch.setattr(defillama_mod, "get_chain_data", fake_chain)
    monkeypatch.setattr(defillama_mod, "get_historical_chain_data", fake_hist)
    key = "defillama_eth"
    if key in defillama_mod.cache:
        del defillama_mod.cache[key]
    await defillama_mod.fetch_defillama_tvl("eth", cache_ttl=1)
    miss_val = defillama_mod.DEFI_LLAMA_CACHE_MISS._value.get()  # type: ignore[attr-defined]
    await defillama_mod.fetch_defillama_tvl("eth", cache_ttl=1)
    hit_val = defillama_mod.DEFI_LLAMA_CACHE_HIT._value.get()  # type: ignore[attr-defined]
    assert hit_val >= 1 and miss_val >= 1


def test_market_cache_metrics(monkeypatch):
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
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: payload})()
    monkeypatch.setattr(httpx, 'get', fake_get)
    key = "market_cacheasset"
    if key in market_mod.cache:
        del market_mod.cache[key]
    market_mod.fetch_market("cacheasset")
    market_mod.fetch_market("cacheasset")
    assert market_mod.MARKET_CACHE_HIT._value.get() >= 1  # type: ignore[attr-defined]
    assert market_mod.MARKET_CACHE_MISS._value.get() >= 1  # type: ignore[attr-defined]

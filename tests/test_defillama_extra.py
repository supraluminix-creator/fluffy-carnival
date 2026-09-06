import pytest

from pipeline.collectors import defillama as defillama_mod


@pytest.mark.asyncio
async def test_defillama_no_chain_data(monkeypatch):
    async def fake_chain(chain: str):
        return None  # force branche 'no chain data'

    monkeypatch.setattr(defillama_mod, "get_chain_data", fake_chain)
    res = await defillama_mod.fetch_defillama_tvl("ghostchain", cache_ttl=1)
    assert res is None


@pytest.mark.asyncio
async def test_defillama_invalid_tvl_type(monkeypatch):
    async def fake_chain(chain: str):
        return {"name": chain, "tvl": {"nested": 1}}  # tvl type invalide

    async def fake_hist(chain: str):
        return []

    monkeypatch.setattr(defillama_mod, "get_chain_data", fake_chain)
    monkeypatch.setattr(defillama_mod, "get_historical_chain_data", fake_hist)
    res = await defillama_mod.fetch_defillama_tvl("eth", cache_ttl=1)
    assert res is None


@pytest.mark.asyncio
async def test_defillama_historical_parse_errors(monkeypatch):
    async def fake_chain(chain: str):
        return {"name": chain, "tvl": 10}

    # Historical data with malformed entries to exercise parse warnings
    malformed = [
        {"date": "not-a-timestamp", "tvl": "x"},
        ["bad", "yy"],
        {"wrong_key": 123},
    ]

    async def fake_hist(chain: str):
        return malformed

    monkeypatch.setattr(defillama_mod, "get_chain_data", fake_chain)
    monkeypatch.setattr(defillama_mod, "get_historical_chain_data", fake_hist)
    res = await defillama_mod.fetch_defillama_tvl("polygon", cache_ttl=1)
    assert res is not None
    assert res["value"]["tvl"] == 10

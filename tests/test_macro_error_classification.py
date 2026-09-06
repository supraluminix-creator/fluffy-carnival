import httpx
import pytest
from prometheus_client import REGISTRY

from pipeline.collectors.market import fetch_macro


class DummyResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


def _collector_errors_total(collector: str) -> float:
    m = REGISTRY._names_to_collectors.get("collector_error_types_total")
    if not m:
        return 0.0
    total = 0.0
    for fam in m.collect():
        for s in fam.samples:
            if s.name == "collector_error_types_total" and s.labels.get("collector") == collector:
                total += s.value
    return total


@pytest.mark.asyncio
async def test_macro_cg_network_then_cmc_schema(monkeypatch):
    import pipeline.collectors.market as market

    # 1) CoinGecko network failure
    calls = {"cg": 0, "cmc": 0}

    async def fake_async_get_json(client, url, timeout=10):
        calls["cg"] += 1
        raise httpx.RequestError("connect fail")

    # 2) CMC returns malformed structure (no data key) -> schema
    def fake_httpx_get(url, headers=None):
        calls["cmc"] += 1
        return DummyResp({"status": {"timestamp": "ts"}}, status=200)

    monkeypatch.setattr(market, "_async_http_get_json", fake_async_get_json)
    monkeypatch.setattr(httpx, "get", fake_httpx_get)

    before_errors = _collector_errors_total("macro")

    res = await fetch_macro("bitcoin")
    # Le code actuel renvoie un enregistrement coinmarketcap fallback même si la structure CMC est partielle.
    assert isinstance(res, dict) and res.get("source") == "coinmarketcap"

    after_errors = _collector_errors_total("macro")
    # Au moins une erreur (CoinGecko) a été enregistrée
    assert after_errors == before_errors + 1
    # Vérifie que CMC a bien été tenté après CG
    assert calls["cg"] == 1
    assert calls["cmc"] == 1

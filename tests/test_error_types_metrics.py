import os
import re
from prometheus_client import REGISTRY

# Tests ciblés sur métrique collector_error_types_total

def _find_metric_samples(name: str):
    m = REGISTRY._names_to_collectors.get(name)
    if not m:
        return []
    samples = []
    for fam in m.collect():
        for s in fam.samples:
            samples.append(s)
    return samples


def test_error_type_counter_market(monkeypatch):
    # Force erreurs sur primary + fallback -> 2 types potentiels
    import pipeline.collectors.market as market
    calls = {"cg":0, "cmc":0}

    def fake_get_fail(url, timeout=10, headers=None):
        # Simuler rate limit sur CG et network sur CMC
        if "coingecko" in url:
            calls["cg"] += 1
            raise RuntimeError("RateLimitExceeded")
        if "coinmarketcap" in url:
            calls["cmc"] += 1
            raise ConnectionError("connect fail")
    monkeypatch.setattr(market.httpx, "get", fake_get_fail)
    res = market.fetch_market("bitcoin")
    assert res is None
    samples = _find_metric_samples("collector_error_types_total")
    # Cherche au moins les 2 catégories rate_limit & network
    labels = [dict(s.labels) for s in samples if s.name=="collector_error_types_total"]
    assert any(l.get("error_type") == "rate_limit" and l.get("collector")=="market" for l in labels)
    assert any(l.get("error_type") == "network" and l.get("collector")=="market" for l in labels)


def test_error_type_counter_deriv_oi(monkeypatch):
    import pipeline.collectors.derivatives as deriv

    async def fake_client_get_fail(self, url, params=None, timeout=10):
        raise TimeoutError("request timedout")

    class FakeResp:
        status_code=500
        def json(self):
            return {}
        def raise_for_status(self):
            raise ValueError("schema broken")

    async def fake_client_get_schema(self, url, params=None, timeout=10):
        return FakeResp()

    # Bybit primary timeouts
    monkeypatch.setattr(deriv.httpx.AsyncClient, "get", fake_client_get_fail)
    import asyncio
    res = asyncio.run(deriv.fetch_bybit_oi("BTCUSDT"))
    assert res is None
    # Ajuster pour fallback second échec schema
    monkeypatch.setattr(deriv.httpx.AsyncClient, "get", fake_client_get_schema)
    res2 = asyncio.run(deriv.fetch_bybit_oi("BTCUSDT"))
    assert res2 is None
    samples = _find_metric_samples("collector_error_types_total")
    labels = [dict(s.labels) for s in samples if s.name=="collector_error_types_total"]
    # On attend timeout + (schema OU upstream) selon implémentation (façade HTTP convertit 500 en upstream)
    assert any(l.get("error_type") == "timeout" and l.get("collector")=="deriv_oi" for l in labels)
    assert any(l.get("error_type") in ("schema", "upstream") and l.get("collector")=="deriv_oi" for l in labels)

import httpx
import pytest
from prometheus_client import REGISTRY


class DummyResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code != 200:
            raise httpx.HTTPStatusError("err", request=None, response=None)


@pytest.mark.asyncio
async def test_macro_latency_histogram(monkeypatch):
    # Force CG failure
    async def fail_async_json(client, url, timeout=10):
        raise RuntimeError("cg down")

    monkeypatch.setattr("pipeline.collectors.market._async_http_get_json", fail_async_json)

    # Force CMC success via sync path
    def fake_httpx_get(url, headers=None, timeout=10):
        return DummyResp(
            {
                "status": {"timestamp": "2025-09-21T02:00:00Z"},
                "data": {
                    "BITCOIN": {
                        "quote": {
                            "USD": {
                                "price": 60000,
                                "volume_24h": 1500,
                                "market_cap": 920000000,
                                "market_cap_dominance": 57.0,
                            }
                        }
                    }
                },
            }
        )

    monkeypatch.setattr(httpx, "get", fake_httpx_get)
    from pipeline.collectors.market import fetch_macro

    rec = await fetch_macro("bitcoin")
    assert rec and rec["source"] == "coinmarketcap"
    coll = getattr(REGISTRY, "_names_to_collectors", {}).get("fallback_tier_latency_seconds")
    assert coll is not None, "Histogram fallback_tier_latency_seconds not registered"
    found = False
    for metric in coll.collect():
        for s in metric.samples:
            if (
                s.name.endswith("_bucket")
                and s.labels.get("collector") == "macro"
                and s.labels.get("tier") == "2"
                and s.labels.get("status") == "success"
                and s.value > 0
            ):
                found = True
    assert found, "Expected latency bucket sample for macro tier=2 success"


@pytest.mark.asyncio
async def test_deriv_oi_latency_histogram(monkeypatch):
    from pipeline.collectors.derivatives import fetch_bybit_oi

    # Patch AsyncClient.get to fail first (Bybit) then succeed (Binance hist)
    call_state = {"n": 0}

    async def conditional_get(self, url, params=None, timeout=10):
        call_state["n"] += 1
        if "open-interest" in url:
            raise httpx.HTTPError("bybit down")
        if "openInterestHist" in url:
            return DummyResp([{"timestamp": "1700000000000", "sumOpenInterest": "123"}])
        raise AssertionError("Unexpected URL " + url)

    monkeypatch.setattr(httpx.AsyncClient, "get", conditional_get)
    rec = await fetch_bybit_oi("BTCUSDT")
    assert rec and rec["source"] != "bybit"
    coll = getattr(REGISTRY, "_names_to_collectors", {}).get("fallback_tier_latency_seconds")
    assert coll is not None
    found = False
    for metric in coll.collect():
        for s in metric.samples:
            if (
                s.name.endswith("_bucket")
                and s.labels.get("collector") == "deriv_oi"
                and s.labels.get("tier") == "2"
                and s.labels.get("status") == "success"
                and s.value > 0
            ):
                found = True
    assert found, "Expected latency bucket sample for deriv_oi tier=2 success"

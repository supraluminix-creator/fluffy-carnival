import httpx
import pytest
from prometheus_client import REGISTRY

from pipeline.collectors.derivatives import fetch_bybit_oi


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
async def test_macro_tier_metric(monkeypatch):
    # Force CG failure by patching helper used in CoinGecko path
    async def fail_async_json(client, url, timeout=10):
        raise RuntimeError("cg down")

    monkeypatch.setattr("pipeline.collectors.market._async_http_get_json", fail_async_json)

    # Provide CMC success via sync path (patch httpx.get so detection chooses sync)
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
    # Scrape metrics
    # Retrieve collector (some prometheus versions may not yield untouched counters in collect list here)
    coll = getattr(REGISTRY, "_names_to_collectors", {}).get("fallback_tier_invocations_total")
    assert coll is not None, "Metric fallback_tier_invocations_total not registered"
    found = False
    for metric in coll.collect():
        for s in metric.samples:
            if (
                s.labels.get("collector") == "macro"
                and s.labels.get("tier") == "2"
                and s.labels.get("status") == "success"
            ):
                found = True
    assert found, "Expected macro tier=2 success sample"


@pytest.mark.asyncio
async def test_deriv_oi_tier_metric(monkeypatch):
    # Conditional async get: first (Bybit) fails, second (Binance hist) succeeds
    call_state = {"n": 0}

    async def conditional_get(self, url, params=None, timeout=10):
        call_state["n"] += 1
        if "open-interest" in url:
            raise httpx.HTTPError("bybit down")
        if "openInterestHist" in url:
            return DummyResp([{"timestamp": "1700000000000", "sumOpenInterest": "123"}])
        raise AssertionError("Unexpected URL in conditional_get: " + url)

    monkeypatch.setattr(httpx.AsyncClient, "get", conditional_get)
    rec = await fetch_bybit_oi("BTCUSDT")
    assert rec and rec["source"] != "bybit"
    coll = getattr(REGISTRY, "_names_to_collectors", {}).get("fallback_tier_invocations_total")
    assert coll is not None
    found = False
    for metric in coll.collect():
        for s in metric.samples:
            if (
                s.labels.get("collector") == "deriv_oi"
                and s.labels.get("tier") == "2"
                and s.labels.get("status") == "success"
            ):
                found = True
    assert found, "Expected deriv_oi tier=2 success sample"

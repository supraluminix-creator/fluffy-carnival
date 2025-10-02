import httpx
import pytest

from pipeline import circuit_breaker as cb
from pipeline.collectors import derivatives, market


class DummyResp:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
        self.request = httpx.Request('GET', 'http://dummy')
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError('err', request=self.request, response=httpx.Response(self.status_code, request=self.request))
    def json(self):
        return self._json


@pytest.mark.asyncio
async def test_fetch_macro_cache_and_breaker(monkeypatch):
    # Reset breaker and cache state
    cb.reset('market_macro')
    # Ensure empty cache
    market.cache.clear()

    # First call: simulate successful coingecko response
    data = {"market_data": {"current_price": {"usd": 100}, "total_volume": {"usd": 10}, "market_cap": {"usd": 1000}, "market_cap_rank": 1}, "last_updated": "2025-01-01T00:00:00Z"}
    async def fake_async_get(self, url, timeout=10):  # noqa: ARG002
        return DummyResp(data)
    class DummyAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return False
        get = fake_async_get
    monkeypatch.setattr(market.httpx, 'AsyncClient', lambda: DummyAsyncClient())
    result1 = await market.fetch_macro('bitcoin')
    assert result1 and result1['value']['price'] == 100.0

    # Second call should hit cache (no need to patch differently)
    result2 = await market.fetch_macro('bitcoin')
    assert result2 == result1

    # Force breaker open then skip
    st = cb._get('market_macro')
    st.fail_count = st.threshold  # open condition next check
    st.opened_at = 0  # force open state
    # monkeypatch time to keep breaker open
    monkeypatch.setattr(cb, 'time', lambda: 1)
    skipped = await market.fetch_macro('bitcoin')
    assert skipped is None


def test_fetch_market_cache_and_fallback(monkeypatch):
    cb.reset('market_main')
    market.cache.clear()

    # Simulate primary success path
    data = {"market_data": {"current_price": {"usd": 200}, "total_volume": {"usd": 20}, "market_cap": {"usd": 2000}, "market_cap_rank": 2}}
    def fake_get(url, timeout=10):  # noqa: ARG002
        return DummyResp(data)
    monkeypatch.setattr(market.httpx, 'get', fake_get)
    res1 = market.fetch_market('bitcoin')
    assert res1 and res1['price'] == 200.0
    # Cache hit
    res2 = market.fetch_market('bitcoin')
    assert res2 == res1

@pytest.mark.asyncio
async def test_derivatives_open_interest_and_lsr(monkeypatch):
    cb.reset('deriv_oi')
    cb.reset('deriv_lsr')
    derivatives.cache.clear()

    # Stub AsyncClient for OI
    oi_payload = {"result": {"list": [{"timestamp": 1, "openInterest": "123.45"}]}}
    lsr_payload = {"result": {"list": [{"timestamp": 2, "buyRatio": "0.6", "sellRatio": "0.4"}]}}
    async def fake_get_oi(self, url, params=None, timeout=10):  # noqa: ARG002
        return DummyResp(oi_payload)
    async def fake_get_lsr(self, url, params=None, timeout=10):  # noqa: ARG002
        return DummyResp(lsr_payload)
    class DummyAsyncClientOI:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return False
        get = fake_get_oi
    class DummyAsyncClientLSR:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return False
        get = fake_get_lsr

    monkeypatch.setattr(derivatives.httpx, 'AsyncClient', lambda: DummyAsyncClientOI())
    oi_res = await derivatives.fetch_bybit_oi('BTCUSDT')
    assert oi_res and oi_res['value'] == 123.45

    monkeypatch.setattr(derivatives.httpx, 'AsyncClient', lambda: DummyAsyncClientLSR())
    lsr_res = await derivatives.fetch_bybit_long_short_ratio('BTCUSDT')
    assert lsr_res and lsr_res['value']['buy_ratio'] == 0.6

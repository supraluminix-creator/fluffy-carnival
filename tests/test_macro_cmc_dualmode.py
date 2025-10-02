import httpx
import pytest

from pipeline.collectors.market import fetch_macro


class DummyResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}
    def json(self):
        return self._json

@pytest.mark.asyncio
async def test_macro_cmc_async_path(monkeypatch):
    # Force CG failure
    async def fake_async_get_json(client, url, timeout=10):
        raise RuntimeError("cg down")
    monkeypatch.setattr("pipeline.collectors.market._async_http_get_json", fake_async_get_json)

    # Ensure httpx.get is original so async path for CMC chosen
    def fake_client_get(self, url, headers=None, timeout=10):
        # simulate CMC success
        return DummyResp(200, {
            "status": {"timestamp": "2025-09-21T00:00:00Z"},
            "data": {"BITCOIN": {"quote": {"USD": {"price": 50000, "volume_24h": 1000, "market_cap": 900000000, "market_cap_dominance": 55.0}}}}
        })
    class DummyAsyncClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def get(self, url, headers=None, timeout=10):
            return fake_client_get(self, url, headers, timeout)
    monkeypatch.setattr(httpx, 'AsyncClient', DummyAsyncClient)

    rec = await fetch_macro(symbol="bitcoin")
    assert rec is not None
    assert rec['source'] == 'coinmarketcap'
    assert rec['value']['price'] == 50000

@pytest.mark.asyncio
async def test_macro_cmc_sync_path(monkeypatch):
    # Force CG failure
    async def fake_async_get_json(client, url, timeout=10):
        raise RuntimeError("cg down")
    monkeypatch.setattr("pipeline.collectors.market._async_http_get_json", fake_async_get_json)

    # Monkeypatch httpx.get to trigger sync detection
    def fake_httpx_get(url, headers=None, timeout=10):
        return DummyResp(200, {
            "status": {"timestamp": "2025-09-21T01:00:00Z"},
            "data": {"BITCOIN": {"quote": {"USD": {"price": 51000, "volume_24h": 1200, "market_cap": 910000000, "market_cap_dominance": 56.0}}}}
        })
    monkeypatch.setattr(httpx, 'get', fake_httpx_get)

    rec = await fetch_macro(symbol="bitcoin")
    assert rec is not None
    assert rec['source'] == 'coinmarketcap'
    assert rec['value']['price'] == 51000

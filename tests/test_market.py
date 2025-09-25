from typing import Any

import httpx
import pytest

from pipeline.collectors.market import fetch_macro, fetch_market


class DummyResp:
    def __init__(self, payload: Any):
        self._payload = payload
    def raise_for_status(self) -> None:  # pragma: no cover
        return
    def json(self):
        return self._payload


def test_fetch_market_success(monkeypatch):
    payload = {
        "market_data": {
            "current_price": {"usd": 1.23},
            "total_volume": {"usd": 2},
            "market_cap": {"usd": 3},
            "market_cap_rank": 7,
        }
    }
    def fake_get(url: str, timeout: int = 10):  # noqa: D401
        return DummyResp(payload)
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_market('bitcoinmk1')
    assert rec is not None
    assert rec['price'] == 1.23
    assert rec['dominance'] == 7


def test_fetch_market_fallback(monkeypatch):
    # Primary raises -> fallback path
    def fake_get(url: str, timeout: int = 10):  # noqa: D401
        if 'coingecko' in url:
            raise RuntimeError('primary fail')
        return DummyResp({
            'data': {'BITCOINMK2': {'quote': {'USD': {
                'price': 10.0,
                'volume_24h': 20.0,
                'market_cap': 30.0,
                'market_cap_dominance': 40.0,
            }}}}
        })
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_market('bitcoinmk2')
    assert rec is not None
    assert rec['price'] == 10.0
    assert rec['dominance'] == 40.0


class DummyAsyncClient:
    def __init__(self, payload_map: dict[str, Any]):
        self.payload_map = payload_map
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    async def get(self, url: str, headers: dict[str, str] | None = None, timeout: int = 10):
        payload = self.payload_map[url]
        if isinstance(payload, Exception):
            raise payload
        return DummyResp(payload)


@pytest.mark.asyncio
async def test_fetch_macro_success(monkeypatch):
    coingecko_url = 'https://api.coingecko.com/api/v3/coins/bitcoinmc1'
    payload = {
        'last_updated': '2025-09-20T00:00:00Z',
        'market_data': {
            'current_price': {'usd': 100.0},
            'total_volume': {'usd': 200.0},
            'market_cap': {'usd': 300.0},
            'market_cap_rank': 5,
        }
    }
    def factory(*a, **k):
        return DummyAsyncClient({coingecko_url: payload})
    monkeypatch.setattr(httpx, 'AsyncClient', factory)
    rec = await fetch_macro('bitcoinmc1')
    assert rec is not None
    assert rec['value']['price'] == 100.0
    assert rec['source'] == 'coingecko'


@pytest.mark.asyncio
async def test_fetch_macro_fallback(monkeypatch):
    coingecko_url = 'https://api.coingecko.com/api/v3/coins/bitcoinmc2'
    cmc_url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol=BITCOINMC2'
    fallback_payload = {
        'status': {'timestamp': '2025-09-20T01:00:00Z'},
        'data': {'BITCOINMC2': {'quote': {'USD': {
            'price': 150.0,
            'volume_24h': 250.0,
            'market_cap': 350.0,
            'market_cap_dominance': 45.0,
        }}}}
    }
    def factory(*a, **k):
        return DummyAsyncClient({
            coingecko_url: RuntimeError('primary fail'),
            cmc_url: fallback_payload,
        })
    monkeypatch.setattr(httpx, 'AsyncClient', factory)
    rec = await fetch_macro('bitcoinmc2', cmc_api_key='X')
    assert rec is not None
    assert rec['source'] == 'coinmarketcap'
    assert rec['value']['price'] == 150.0


@pytest.mark.asyncio
async def test_fetch_macro_no_key(monkeypatch):
    coingecko_url = 'https://api.coingecko.com/api/v3/coins/bitcoinmc3'
    def factory(*a, **k):
        return DummyAsyncClient({coingecko_url: RuntimeError('primary fail')})
    monkeypatch.setattr(httpx, 'AsyncClient', factory)
    rec = await fetch_macro('bitcoinmc3')
    assert rec is None

import httpx
import pytest

from pipeline.collectors.onchain import cache, fetch_txcount


class DummyAsyncResponse:
    def __init__(self, status_code: int = 200, text: str | None = None, json_data=None):
        self.status_code = status_code
        self.text = text or ""
        self._json_data = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class DummyAsyncClient:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, timeout=10):
        self.calls.append(url)
        value = self.mapping.get(url)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, dict):
            return DummyAsyncResponse(json_data=value)
        if isinstance(value, int):
            return DummyAsyncResponse(text=str(value))
        if isinstance(value, str):
            return DummyAsyncResponse(text=value)
        return DummyAsyncResponse(text="123")


@pytest.mark.asyncio
async def test_txcount_btc_primary_success(monkeypatch):
    cache.clear()
    url_main = "https://api.blockchain.info/q/getblockcount"
    client = DummyAsyncClient({url_main: 123456})
    monkeypatch.setattr(httpx, "AsyncClient", lambda: client)
    rec = await fetch_txcount("BTC")
    assert rec is not None and rec["source"] == "blockchain.info" and rec["value"] == 123456
    # Cache hit second call (no additional HTTP call)
    client.calls.clear()
    rec2 = await fetch_txcount("BTC")
    assert rec2 is not None
    assert client.calls == []


@pytest.mark.asyncio
async def test_txcount_btc_primary_failure_fallback_success(monkeypatch):
    cache.clear()
    url_main = "https://api.blockchain.info/q/getblockcount"
    # used as fallback for BTC if provided
    etherscan = "https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey=KEY"
    # Primary raises, fallback returns hex block number
    client = DummyAsyncClient({url_main: RuntimeError("fail"), etherscan: {"result": hex(0xABCDEF)}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda: client)
    rec = await fetch_txcount("BTC", etherscan_api_key="KEY")
    assert rec is not None and rec["source"] == "etherscan" and rec["value"] == 0xABCDEF
    assert url_main in client.calls and etherscan in client.calls


@pytest.mark.asyncio
async def test_txcount_btc_primary_failure_fallback_failure(monkeypatch):
    cache.clear()
    url_main = "https://api.blockchain.info/q/getblockcount"
    etherscan = "https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey=KEY"
    client = DummyAsyncClient({url_main: RuntimeError("fail"), etherscan: RuntimeError("fb_fail")})
    monkeypatch.setattr(httpx, "AsyncClient", lambda: client)
    rec = await fetch_txcount("BTC", etherscan_api_key="KEY")
    assert rec is None


@pytest.mark.asyncio
async def test_txcount_eth_requires_key(monkeypatch):
    cache.clear()
    # Calling ETH without key triggers main error path and final None
    url_eth = "https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey=None"
    client = DummyAsyncClient({url_eth: {"result": hex(100)}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda: client)
    rec = await fetch_txcount("ETH")
    assert rec is None


@pytest.mark.asyncio
async def test_txcount_eth_success(monkeypatch):
    cache.clear()
    url_eth = "https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey=K1"
    client = DummyAsyncClient({url_eth: {"result": hex(0x10)}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda: client)
    rec = await fetch_txcount("ETH", etherscan_api_key="K1")
    assert rec is not None and rec["value"] == 0x10 and rec["source"] == "etherscan"


@pytest.mark.asyncio
async def test_txcount_eth_failure_no_fallback(monkeypatch):
    cache.clear()
    url_eth = "https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey=K2"
    client = DummyAsyncClient({url_eth: RuntimeError("err")})
    monkeypatch.setattr(httpx, "AsyncClient", lambda: client)
    rec = await fetch_txcount("ETH", etherscan_api_key="K2")
    assert rec is None


@pytest.mark.asyncio
async def test_txcount_btc_cache_prevents_fallback_second_call(monkeypatch):
    cache.clear()
    url_main = "https://api.blockchain.info/q/getblockcount"
    etherscan = "https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey=KEY"
    client = DummyAsyncClient({url_main: RuntimeError("fail"), etherscan: {"result": hex(0x77)}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda: client)
    rec = await fetch_txcount("BTC", etherscan_api_key="KEY")
    assert rec is not None and rec["value"] == 0x77
    # Now second call should hit cache only
    client.calls.clear()
    rec2 = await fetch_txcount("BTC", etherscan_api_key="KEY")
    assert rec2 is not None and client.calls == []

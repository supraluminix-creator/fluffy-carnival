from typing import Any

import httpx
import pytest

from pipeline.collectors.onchain import fetch_hashrate, fetch_sopr, fetch_txcount


class DummyResp:
    def __init__(self, text: str | None = None, json_payload: Any | None = None, error: Exception | None = None):
        self._text = text
        self._json = json_payload
        self._error = error
    def raise_for_status(self) -> None:  # pragma: no cover
        if self._error:
            raise self._error
    @property
    def text(self) -> str:
        return self._text or ""
    def json(self):
        return self._json

class DummyAsyncClient:
    def __init__(self, sequence: list[tuple[str, DummyResp]]):
        self.sequence = sequence
        self.calls: list[str] = []
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    async def get(self, url: str, timeout: int = 10):  # noqa: D401
        self.calls.append(url)
        for pattern, resp in self.sequence:
            if pattern in url:
                return resp
        raise RuntimeError(f"Unexpected URL {url}")

# --- fetch_txcount ---

@pytest.mark.asyncio
async def test_fetch_txcount_btc_success(monkeypatch):
    client = DummyAsyncClient([
        ("blockchain.info", DummyResp(text="123456")),
    ])
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: client)
    rec = await fetch_txcount("BTC")
    assert rec is not None
    assert rec['metric_name'] == 'txcount'
    assert rec['value'] == 123456

@pytest.mark.asyncio
async def test_fetch_txcount_eth_success(monkeypatch):
    client = DummyAsyncClient([
        ("etherscan.io", DummyResp(json_payload={"result": "0x10"})),
    ])
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: client)
    rec = await fetch_txcount("ETH", etherscan_api_key="X")
    assert rec is not None
    assert rec['value'] == 16

@pytest.mark.asyncio
async def test_fetch_txcount_eth_missing_key(monkeypatch):
    client = DummyAsyncClient([
        ("etherscan.io", DummyResp(json_payload={"result": "0x11"})),
    ])
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: client)
    rec = await fetch_txcount("ETH")
    assert rec is None

# --- fetch_hashrate ---

@pytest.mark.asyncio
async def test_fetch_hashrate_success(monkeypatch):
    client = DummyAsyncClient([
        ("hashrate", DummyResp(text="123.45")),
    ])
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: client)
    rec = await fetch_hashrate("BTC")
    assert rec is not None
    assert rec['metric_name'] == 'hashrate'
    assert rec['value'] == 123.45

# --- fetch_sopr ---

@pytest.mark.asyncio
async def test_fetch_sopr_success(monkeypatch):
    csv_text = "unixTs,sopr\n1700000000,1.05\n1700000060,0.98\n"
    client = DummyAsyncClient([
        ("bitcoin-data.com", DummyResp(text=csv_text)),
    ])
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: client)
    rec = await fetch_sopr("BTC")
    assert rec is not None
    assert rec['metric_name'] == 'sopr'
    assert abs(rec['value'] - 0.98) < 1e-9

@pytest.mark.asyncio
async def test_fetch_sopr_no_valid(monkeypatch):
    csv_text = "unixTs,sopr\n"  # empty values
    client = DummyAsyncClient([
        ("bitcoin-data.com", DummyResp(text=csv_text)),
    ])
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: client)
    rec = await fetch_sopr("BTC")
    assert rec is None

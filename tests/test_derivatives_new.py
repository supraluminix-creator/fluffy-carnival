import asyncio
import os
from types import SimpleNamespace
import pytest
import httpx

import pipeline.collectors.derivatives as dmod
from pipeline.metrics import COLLECTOR_ERROR_TYPES_TOTAL

# --- Helpers ---
class DummyResp:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
    def json(self):
        return self._data
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=SimpleNamespace(url='u'), response=SimpleNamespace(status_code=self.status_code))

class FakeAsyncClient:
    def __init__(self, script):
        # script: list of (match_substring, response|exception)
        self.script = script
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    async def get(self, url, params=None, timeout=10, headers=None):  # pragma: no cover (exercised)
        for match, value in self.script:
            if match in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"No scripted response for {url}")

@pytest.mark.asyncio
async def test_deriv_oi_primary_success(monkeypatch):
    # Bybit success path (list non vide)
    bybit_data = {"result": {"list": [{"timestamp": "1700000000000", "openInterest": "123.45"}]}}
    script = [("open-interest", DummyResp(bybit_data))]
    monkeypatch.setattr(dmod, 'httpx', SimpleNamespace(AsyncClient=lambda: FakeAsyncClient(script)))
    rec = await dmod.fetch_bybit_oi('BTCUSDT')
    assert rec is not None and rec['source'] == 'bybit' and rec['value'] == pytest.approx(123.45)

@pytest.mark.asyncio
async def test_deriv_oi_primary_upstream_fallback_binance(monkeypatch):
    # Primary raises upstream (502) then fallback binance hist success
    bybit_exc = httpx.HTTPStatusError("bad", request=SimpleNamespace(url='u'), response=SimpleNamespace(status_code=502))
    binance_hist = [ {"sumOpenInterest": "222.2", "timestamp": 1700000001111} ]
    script1 = [("open-interest", bybit_exc)]
    script2 = [("openInterestHist", DummyResp(binance_hist))]
    # Sequence: first AsyncClient for bybit, second for binance hist
    clients = [FakeAsyncClient(script1), FakeAsyncClient(script2)]
    def client_factory():
        return clients.pop(0)
    monkeypatch.setattr(dmod, 'httpx', SimpleNamespace(AsyncClient=client_factory))
    rec = await dmod.fetch_bybit_oi('ETHUSDT')
    assert rec is not None and rec['source'] == 'binance' and rec['value'] == pytest.approx(222.2)

@pytest.mark.asyncio
async def test_deriv_oi_primary_rate_limit_metric(monkeypatch):
    # Primary returns 429 -> classification rate_limit -> no fallback invoked due to early exception then fallback attempts
    rate_exc = httpx.HTTPStatusError("rl", request=SimpleNamespace(url='u'), response=SimpleNamespace(status_code=429))
    script1 = [("open-interest", rate_exc)]
    script2 = [("openInterestHist", DummyResp([]))]  # fallback returns empty -> error path
    clients = [FakeAsyncClient(script1), FakeAsyncClient(script2)]
    monkeypatch.setattr(dmod, 'httpx', SimpleNamespace(AsyncClient=lambda: clients.pop(0)))
    before = COLLECTOR_ERROR_TYPES_TOTAL.labels(collector='deriv_oi', error_type='rate_limit')._value.get() if ('deriv_oi','rate_limit') in COLLECTOR_ERROR_TYPES_TOTAL._metrics else 0
    rec = await dmod.fetch_bybit_oi('XRPUSDT')
    assert rec is None
    after = COLLECTOR_ERROR_TYPES_TOTAL.labels(collector='deriv_oi', error_type='rate_limit')._value.get()
    assert after == before + 1

@pytest.mark.asyncio
async def test_deriv_funding_fallback_binance(monkeypatch):
    # Primary funding fails -> fallback uses fetch_binance_funding
    funding_exc = httpx.HTTPStatusError("fund", request=SimpleNamespace(url='u'), response=SimpleNamespace(status_code=500))
    script = [("funding/history", funding_exc)]
    monkeypatch.setattr(dmod, 'httpx', SimpleNamespace(AsyncClient=lambda: FakeAsyncClient(script)))
    # Monkeypatch fallback function from binance collectors
    import pipeline.collectors.binance as bbin
    def fake_binance_funding(symbol):
        return {"timestamp": 1700, "asset": symbol[:-4], "symbol": symbol, "metric_name": "funding_rate", "value": 0.0002, "source": "binance", "confidence_score": 0.8}
    monkeypatch.setattr(bbin, 'fetch_binance_funding', fake_binance_funding)
    monkeypatch.setattr(dmod, 'fetch_binance_funding', fake_binance_funding)
    rec = await dmod.fetch_bybit_funding('BTCUSDT')
    assert rec is not None and rec['source'] == 'binance' and rec['value'] == pytest.approx(0.0002)

@pytest.mark.asyncio
async def test_deriv_lsr_success(monkeypatch):
    lsr_data = {"result": {"list": [{"timestamp": "1700", "buyRatio": "55.5", "sellRatio": "44.5"}]}}
    script = [("account-ratio", DummyResp(lsr_data))]
    monkeypatch.setattr(dmod, 'httpx', SimpleNamespace(AsyncClient=lambda: FakeAsyncClient(script)))
    rec = await dmod.fetch_bybit_long_short_ratio('BTCUSDT')
    assert rec is not None and rec['metric_name'] == 'long_short_ratio'
    assert rec['value']['buy_ratio'] == pytest.approx(55.5)

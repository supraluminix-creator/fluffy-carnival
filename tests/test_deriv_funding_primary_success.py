import pytest
import httpx
from pipeline.collectors.derivatives import fetch_bybit_funding

class DummyResp:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
    def json(self):
        return self._json
    def raise_for_status(self):
        if self.status_code != 200:
            raise httpx.HTTPStatusError("err", request=None, response=None)

@pytest.mark.asyncio
async def test_funding_primary_success(monkeypatch):
    # Ensure breaker closed
    try:
        from pipeline.circuit_breaker import reset
        reset("deriv_funding")
    except Exception:
        pass

    lst = [{"fundingRate": "0.0005", "fundingRateTimestamp": "1700000000000"}]
    async def fake_get(self, url, params=None, timeout=10):
        return DummyResp({"result": {"list": lst}})
    monkeypatch.setattr(httpx.AsyncClient, 'get', fake_get)

    rec = await fetch_bybit_funding('BTCUSDT')
    assert rec is not None
    assert rec['source'] == 'bybit'
    assert rec['metric_name'] == 'funding_rate'
    assert rec['value'] == 0.0005

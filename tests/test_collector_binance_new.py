from types import SimpleNamespace

import httpx
import pytest

import pipeline.collectors.binance as bmod
from pipeline.metrics import COLLECTOR_ERROR_TYPES_TOTAL


class DummyResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data
    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=SimpleNamespace(url='u'), response=SimpleNamespace(status_code=self.status_code))

@pytest.fixture(autouse=True)
def reset_metrics():
    # Pas de reset global simple; on lit valeur avant/après dans tests ciblés
    yield

# --- Spot price succès ---

def test_binance_spot_success(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return DummyResponse(200, {"price": "12345.6"})
    monkeypatch.setattr(bmod, 'httpx', SimpleNamespace(get=fake_get))
    rec = bmod.fetch_binance_spot_price('BTCUSDT')
    assert rec is not None
    assert rec['metric_name'] == 'spot_price_usdt'
    assert rec['value'] == pytest.approx(12345.6)
    assert rec['source'] == 'binance_spot'

# --- Spot schema missing price -> None + métrique schema ---

def test_binance_spot_missing_price(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return DummyResponse(200, {"x": 1})
    monkeypatch.setattr(bmod, 'httpx', SimpleNamespace(get=fake_get))
    before = COLLECTOR_ERROR_TYPES_TOTAL.labels(collector='binance_spot', error_type='schema')._value.get() if ('binance_spot','schema') in COLLECTOR_ERROR_TYPES_TOTAL._metrics else 0
    rec = bmod.fetch_binance_spot_price('ETHUSDT')
    assert rec is None
    after = COLLECTOR_ERROR_TYPES_TOTAL.labels(collector='binance_spot', error_type='schema')._value.get()
    assert after == before + 1

# --- Futures OI success ---

def test_binance_futures_oi_success(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return DummyResponse(200, {"openInterest": "987.65"})
    monkeypatch.setattr(bmod, 'httpx', SimpleNamespace(get=fake_get))
    rec = bmod.fetch_binance_futures_oi('BTCUSDT')
    assert rec is not None and rec['metric_name'] == 'open_interest' and rec['value'] == pytest.approx(987.65)

# --- Futures OI upstream 502 -> None + upstream metric ---

def test_binance_futures_oi_upstream(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return DummyResponse(502, {"error": "bad"})
    monkeypatch.setattr(bmod, 'httpx', SimpleNamespace(get=fake_get))
    before = COLLECTOR_ERROR_TYPES_TOTAL.labels(collector='binance_oi', error_type='upstream')._value.get() if ('binance_oi','upstream') in COLLECTOR_ERROR_TYPES_TOTAL._metrics else 0
    rec = bmod.fetch_binance_futures_oi('BTCUSDT')
    assert rec is None
    after = COLLECTOR_ERROR_TYPES_TOTAL.labels(collector='binance_oi', error_type='upstream')._value.get()
    assert after == before + 1

# --- Funding empty list -> None ---

def test_binance_funding_empty_list(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return DummyResponse(200, [])
    monkeypatch.setattr(bmod, 'httpx', SimpleNamespace(get=fake_get))
    rec = bmod.fetch_binance_funding('BTCUSDT')
    assert rec is None

# --- Funding success ---

def test_binance_funding_success(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return DummyResponse(200, [{"fundingRate": "0.0001", "fundingTime": 1700000000000}])
    monkeypatch.setattr(bmod, 'httpx', SimpleNamespace(get=fake_get))
    rec = bmod.fetch_binance_funding('BTCUSDT')
    assert rec is not None and rec['metric_name'] == 'funding_rate' and rec['value'] == pytest.approx(0.0001)

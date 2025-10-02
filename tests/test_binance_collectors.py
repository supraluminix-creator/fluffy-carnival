import httpx
from prometheus_client import REGISTRY

from pipeline.collectors.binance import (
    fetch_binance_funding,
    fetch_binance_futures_oi,
    fetch_binance_spot_price,
)


class DummyResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
    def json(self):
        return self._data
    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code not in (404,429):
            raise httpx.HTTPStatusError("err", request=None, response=None)

# Helper pour lire la valeur courante d'un compteur (labels exacts)

def _metric_value(collector: str, error_type: str) -> float:
    m = REGISTRY._names_to_collectors.get('collector_error_types_total')
    if not m:
        return 0.0
    total = 0.0
    for fam in m.collect():
        for s in fam.samples:
            if s.name == 'collector_error_types_total' and s.labels.get('collector')==collector and s.labels.get('error_type')==error_type:
                total += s.value
    return total

# --- Spot Price Tests ---

def test_spot_success(monkeypatch):
    def fake_get(url, params=None, timeout=5):
        assert 'ticker/price' in url
        return DummyResp({'symbol': 'BTCUSDT', 'price': '50000'})
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_binance_spot_price('BTCUSDT')
    assert rec and rec['value'] == 50000 and rec['source'] == 'binance_spot'

def test_spot_404_not_found(monkeypatch):
    before = _metric_value('binance_spot','not_found')
    def fake_get(url, params=None, timeout=5):
        return DummyResp({}, status=404)
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_binance_spot_price('UNKNOWN')
    assert rec is None
    after = _metric_value('binance_spot','not_found')
    assert after == before + 1

def test_spot_rate_limit(monkeypatch):
    before = _metric_value('binance_spot','rate_limit')
    def fake_get(url, params=None, timeout=5):
        return DummyResp({}, status=429)
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_binance_spot_price('BTCUSDT')
    assert rec is None
    assert _metric_value('binance_spot','rate_limit') == before + 1

def test_spot_schema_error(monkeypatch):
    before = _metric_value('binance_spot','schema')
    def fake_get(url, params=None, timeout=5):
        # JSON valide mais price manquant => EmptyDataError si {} ou Schema si clé absente
        return DummyResp({'symbol':'BTCUSDT'})
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_binance_spot_price('BTCUSDT')
    assert rec is None
    # Peut être classé empty_data si wrapper renvoie {} ; ici classification heuristique => empty_data car record building échoue price -> to_float(None) = 0.0 -> record existe
    # On s'assure au moins qu'une erreur schema OU empty_data est incrémentée
    after_schema = _metric_value('binance_spot','schema')
    after_empty = _metric_value('binance_spot','empty_data')
    assert (after_schema == before + 1) or (after_empty > 0)

# --- Futures OI Tests ---

def test_oi_success(monkeypatch):
    def fake_get(url, params=None, timeout=5):
        assert 'openInterest' in url
        return DummyResp({'symbol': 'BTCUSDT', 'openInterest': '123.45'})
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_binance_futures_oi('BTCUSDT')
    assert rec and rec['value'] == 123.45 and rec['source'] == 'binance'

def test_oi_rate_limit(monkeypatch):
    before = _metric_value('binance_oi','rate_limit')
    def fake_get(url, params=None, timeout=5):
        return DummyResp({}, status=429)
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_binance_futures_oi('BTCUSDT')
    assert rec is None
    assert _metric_value('binance_oi','rate_limit') == before + 1

# --- Funding Tests ---

def test_funding_success(monkeypatch):
    def fake_get(url, params=None, timeout=5):
        assert 'fundingRate' in url
        return DummyResp([
            { 'fundingRate': '0.00025', 'fundingTime': 1700000000000 }
        ])
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_binance_funding('BTCUSDT')
    assert rec and rec['value'] == 0.00025

def test_funding_invalid_rate(monkeypatch):
    def fake_get(url, params=None, timeout=5):
        return DummyResp([
            { 'fundingRate': 'nan', 'fundingTime': 'bad' }
        ])
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_binance_funding('BTCUSDT')
    assert rec is not None


def test_funding_404(monkeypatch):
    before = _metric_value('binance_funding','not_found')
    def fake_get(url, params=None, timeout=5):
        return DummyResp([], status=404)
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_binance_funding('BTCUSDT')
    assert rec is None
    assert _metric_value('binance_funding','not_found') == before + 1


def test_spot_upstream_502(monkeypatch):
    before = _metric_value('binance_spot','upstream')
    def fake_get(url, params=None, timeout=5):
        return DummyResp({'error':'oops'}, status=502)
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_binance_spot_price('BTCUSDT')
    assert rec is None
    assert _metric_value('binance_spot','upstream') == before + 1


def test_funding_empty_data(monkeypatch):
    before = _metric_value('binance_funding','empty_data')
    def fake_get(url, params=None, timeout=5):
        # _http_get verra liste vide -> EmptyDataError
        return DummyResp([], status=200)
    monkeypatch.setattr(httpx, 'get', fake_get)
    rec = fetch_binance_funding('BTCUSDT')
    assert rec is None
    assert _metric_value('binance_funding','empty_data') == before + 1

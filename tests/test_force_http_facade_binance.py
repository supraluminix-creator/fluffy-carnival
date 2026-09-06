import os


def test_force_http_facade_binance_spot(monkeypatch):
    os.environ["FORCE_HTTP_FACADE"] = "1"
    from pipeline.collectors import binance as b

    calls = {}

    def fake_fetch_json(url, params=None, timeout=5, **k):
        calls["url"] = url
        calls["params"] = params or {}
        return {"symbol": params["symbol"], "price": "25000"}

    monkeypatch.setattr(b, "fetch_json", fake_fetch_json)
    rec = b.fetch_binance_spot_price("BTCUSDT")
    assert rec is not None
    assert calls["params"]["symbol"] == "BTCUSDT"
    # legacy log flag not set for this collector
    assert "binance_spot" not in b._LEGACY_LOGGED


def test_force_http_facade_binance_oi(monkeypatch):
    os.environ["FORCE_HTTP_FACADE"] = "1"
    from pipeline.collectors import binance as b

    calls = {}

    def fake_fetch_json(url, params=None, timeout=5, **k):
        calls["url"] = url
        calls["params"] = params or {}
        return {"openInterest": "123.45"}

    monkeypatch.setattr(b, "fetch_json", fake_fetch_json)
    rec = b.fetch_binance_futures_oi("ETHUSDT")
    assert rec is not None
    assert rec["metric_name"] == "open_interest"
    assert "binance_oi" not in b._LEGACY_LOGGED


def test_force_http_facade_binance_funding(monkeypatch):
    os.environ["FORCE_HTTP_FACADE"] = "1"
    from pipeline.collectors import binance as b

    calls = {}

    def fake_fetch_json(url, params=None, timeout=5, **k):
        calls["url"] = url
        calls["params"] = params or {}
        return [{"fundingRate": "0.00025", "fundingTime": 1700000000000}]

    monkeypatch.setattr(b, "fetch_json", fake_fetch_json)
    rec = b.fetch_binance_funding("BNBUSDT")
    assert rec is not None
    assert rec["metric_name"] == "funding_rate"
    assert "binance_funding" not in b._LEGACY_LOGGED

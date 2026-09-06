from __future__ import annotations

from fastapi.testclient import TestClient

from pipeline.api import app
from pipeline.collectors import whale_insider


def test_whale_insider_endpoint_ok(monkeypatch):
    snapshot = {
        "timestamp": 1_700_000_123,
        "records": [
            {
                "timestamp": 1_700_000_100,
                "metric_name": "insider_whale_balance_total",
                "value": 12_345.6,
                "source": "etherscan",
                "addresses": [
                    {"address": "0xabc", "balance_eth": 10.0},
                    {"address": "0xdef", "balance_eth": 2.3456},
                ],
            },
            {
                "timestamp": 1_700_000_110,
                "metric_name": "hl_position_notional_usd",
                "value": 2_000_000.0,
                "source": "hyperliquid",
                "trader": "alpha",
                "symbol": "BTC",
                "metadata": {"side": "long", "leverage": 15},
            },
        ],
        "meta": {
            "records_count": 2,
            "hyperliquid_records": 1,
            "etherscan_watch_count": 1,
            "hyperliquid_watch_count": 1,
        },
    }
    monkeypatch.setattr(whale_insider, "load_latest_snapshot", lambda: snapshot)

    client = TestClient(app)
    resp = client.get("/api/whales/insider")
    assert resp.status_code == 200
    body = resp.json()
    assert body["timestamp"] == snapshot["timestamp"]
    assert body["meta"]["records_count"] == 2
    assert len(body["records"]) == 2
    assert any(rec.get("metric_name") == "hl_position_notional_usd" for rec in body["records"])


def test_whale_insider_endpoint_missing(monkeypatch):
    monkeypatch.setattr(whale_insider, "load_latest_snapshot", lambda: None)
    client = TestClient(app)
    resp = client.get("/api/whales/insider")
    assert resp.status_code == 404


def test_whale_insider_endpoint_invalid(monkeypatch):
    monkeypatch.setattr(whale_insider, "load_latest_snapshot", lambda: {"timestamp": "bad"})
    client = TestClient(app)
    resp = client.get("/api/whales/insider")
    assert resp.status_code == 500

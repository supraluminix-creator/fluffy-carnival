from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from pipeline import db_adapter
from pipeline.api import app


def _now_run_id():
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def test_post_report_requires_api_key(monkeypatch):
    client = TestClient(app)
    db_adapter._REPORTS.clear()

    # Unset key
    monkeypatch.delenv("API_WRITE_KEY", raising=False)

    payload = {
        "meta": {"asset": "BTC", "run_id": _now_run_id()},
        "technical": {"patterns": ["test"]},
    }
    r = client.post("/api/report", json=payload)
    assert r.status_code == 403


def test_post_report_with_api_key(monkeypatch):
    client = TestClient(app)
    db_adapter._REPORTS.clear()

    monkeypatch.setenv("API_WRITE_KEY", "secret123")
    payload = {
        "meta": {"asset": "BTC", "run_id": _now_run_id()},
        "quant": {"volatility": {"hv": 0.2}},
    }
    r = client.post("/api/report", json=payload, headers={"X-API-KEY": "secret123"})
    assert r.status_code == 201
    body = r.json()
    assert body["meta"]["asset"] == "BTC"

    # Now GET latest should return it
    r2 = client.get("/api/report/latest")
    assert r2.status_code == 200
    assert r2.json()["meta"]["asset"] == "BTC"

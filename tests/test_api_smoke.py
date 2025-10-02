from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from pipeline import db_adapter
from pipeline.api import app
from pipeline.schemas import (
    FundamentalSection,
    QuantSection,
    Report,
    ReportMeta,
    TechnicalSection,
)


def _seed_one_report():
    run_id = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    r = Report(meta=ReportMeta(asset="BTC", run_id=run_id))
    db_adapter.write_report(r)
    return r


def test_latest_not_found_then_ok():
    client = TestClient(app)
    # Reset in-memory store
    db_adapter._REPORTS.clear()

    resp = client.get("/api/report/latest")
    assert resp.status_code == 404

    _seed_one_report()
    resp2 = client.get("/api/report/latest")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["meta"]["asset"] == "BTC"


def test_history_default_interval():
    client = TestClient(app)
    db_adapter._REPORTS.clear()
    _seed_one_report()
    resp = client.get("/api/report/history")
    assert resp.status_code == 200
    arr = resp.json()
    assert isinstance(arr, list) and len(arr) >= 1


def test_quant_404_then_ok():
    client = TestClient(app)
    db_adapter._REPORTS.clear()
    _seed_one_report()
    # quant missing
    resp = client.get("/api/quant")
    assert resp.status_code == 404

    # now seed with quant section
    db_adapter._REPORTS.clear()
    run_id = (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    r = Report(
        meta=ReportMeta(asset="BTC", run_id=run_id),
        quant=QuantSection(volatility={"hv": 0.5}),
    )
    db_adapter.write_report(r)
    resp2 = client.get("/api/quant")
    assert resp2.status_code == 200
    body = resp2.json()
    assert "volatility" in body and isinstance(body["volatility"], dict)


def test_onchain_404_then_ok():
    client = TestClient(app)
    db_adapter._REPORTS.clear()
    _seed_one_report()
    # onchain/technical missing
    resp = client.get("/api/onchain")
    assert resp.status_code == 404

    # now seed with technical section
    db_adapter._REPORTS.clear()
    run_id = (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    r = Report(
        meta=ReportMeta(asset="BTC", run_id=run_id),
        technical=TechnicalSection(patterns=["triangle", "breakout"]),
    )
    db_adapter.write_report(r)
    resp2 = client.get("/api/onchain")
    assert resp2.status_code == 200
    body = resp2.json()
    assert "patterns" in body and isinstance(body["patterns"], list)


def test_fundamental_404_then_ok():
    client = TestClient(app)
    db_adapter._REPORTS.clear()
    _seed_one_report()
    # fundamental missing
    resp = client.get("/api/fundamental")
    assert resp.status_code == 404

    # now seed with fundamental section
    db_adapter._REPORTS.clear()
    run_id = (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    r = Report(
        meta=ReportMeta(asset="BTC", run_id=run_id),
        fundamental=FundamentalSection(macro="soft landing", adoption="growing"),
    )
    db_adapter.write_report(r)
    resp2 = client.get("/api/fundamental")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body.get("macro") == "soft landing"


def test_history_interval_validation():
    client = TestClient(app)
    db_adapter._REPORTS.clear()
    _seed_one_report()
    # invalid interval must be rejected by FastAPI validation (pattern)
    resp = client.get("/api/report/history", params={"interval": "5min"})
    assert resp.status_code == 422


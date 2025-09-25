from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

import pipeline.api as api
from pipeline import db_adapter
from pipeline.schemas import Report, ReportMeta


def make_report(ts: str, asset: str = "BTC") -> Report:
    return Report(meta=ReportMeta(asset=asset, run_id=ts))


def test_history_meta_basic():
    # Préparer quelques rapports
    db_adapter.reset_reports()
    client = TestClient(api.app)
    base = datetime.now(UTC).replace(microsecond=0)
    for _i in range(7):
        ts = base.isoformat().replace("+00:00", "Z")
        db_adapter.write_report(make_report(ts))

    r = client.get("/api/report/history_meta?interval=1h&page=2&page_size=3")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 7
    assert data["page"] == 2
    assert data["page_size"] == 3
    assert data["has_next"] is True
    assert isinstance(data["items"], list)
    assert len(data["items"]) == 3

    # Dernière page
    r2 = client.get("/api/report/history_meta?interval=1h&page=3&page_size=3")
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["has_next"] is False
    assert len(data2["items"]) == 1

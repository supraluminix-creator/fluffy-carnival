from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

import pipeline.api as api
from pipeline import db_adapter
from pipeline.schemas import Report, ReportMeta


def make_report(ts: str, asset: str = "BTC") -> Report:
    return Report(meta=ReportMeta(asset=asset, run_id=ts))


def test_history_simple_with_pagination_headers():
    db_adapter.reset_reports()
    client = TestClient(api.app)
    base = datetime.now(UTC).replace(microsecond=0)
    for _i in range(5):
        ts = base.isoformat().replace("+00:00", "Z")
        db_adapter.write_report(make_report(ts))

    r = client.get("/api/report/history?interval=1h&page=1&page_size=2")
    assert r.status_code == 200
    assert r.headers.get("X-Total-Count") == "5"
    assert r.headers.get("X-Has-Next") == "true"
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2

    r2 = client.get("/api/report/history?interval=1h&page=3&page_size=2")
    assert r2.status_code == 200
    assert r2.headers.get("X-Has-Next") == "false"
    data2 = r2.json()
    assert len(data2) == 1

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

import pipeline.api as api
from pipeline import db_adapter
from pipeline.schemas import Report, ReportMeta


def make_report(ts: str, asset: str = "BTC") -> Report:
    return Report(meta=ReportMeta(asset=asset, run_id=ts))


def test_history_pagination_basic():
    db_adapter.reset_reports()
    client = TestClient(api.app)

    # Insert 10 reports in last hour
    base = datetime.now(UTC).replace(microsecond=0)
    for _i in range(10):
        ts = (base).isoformat().replace("+00:00", "Z")
        db_adapter.write_report(make_report(ts))

    r = client.get("/api/report/history?interval=1h&page=1&page_size=3")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 3

    r2 = client.get("/api/report/history?interval=1h&page=2&page_size=3")
    assert r2.status_code == 200
    data2 = r2.json()
    assert len(data2) == 3

    r3 = client.get("/api/report/history?interval=1h&page=4&page_size=3")
    assert r3.status_code == 200
    data3 = r3.json()
    # Remaining 1 (10 total)
    assert len(data3) == 1

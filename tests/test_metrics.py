import os
import time
import asyncio
from contextlib import suppress

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from pipeline.metrics import (
    EXPORTS_TOTAL,
    EXPORT_ROWS_TOTAL,
    COLLECTOR_RUNS_TOTAL,
    COLLECTOR_DURATION_SECONDS,
    HEARTBEAT_TICKS_TOTAL,
    HEALTH_REQUESTS_TOTAL,
    collector_timing,
)
from pipeline.export_utils import export_csv_rows


def parse_metric(text: bytes, metric: str) -> int:
    lines = text.decode().splitlines()
    total = 0
    for l in lines:
        if l.startswith(metric):
            try:
                total += int(float(l.split()[-1]))
            except Exception:
                pass
    return total


def test_export_metrics(tmp_path, monkeypatch):
    # Success
    fn = tmp_path / "test.csv"
    rows = [
        {
            "timestamp": "t",
            "asset": "BTC",
            "symbol": "btc",
            "chain": None,
            "metric_name": "macro",
            "value": 1,
            "source": "test",
            "confidence_score": 1.0,
        }
    ]
    count = export_csv_rows(rows, str(fn))
    assert count == 1

    # Error path: make file unwritable (simulate permission error)
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(PermissionError("no")))
    count2 = export_csv_rows(rows, str(fn))
    assert count2 == 0

    data = generate_latest()
    assert b"pipeline_exports_total" in data
    # At least one success and one error label should appear
    assert b'status="success"' in data
    assert b'status="error"' in data


def test_collector_timing_metrics():
    start_success = COLLECTOR_RUNS_TOTAL.labels(collector="dummy", status="success")._value.get()
    with collector_timing("dummy"):
        time.sleep(0.05)
    end_success = COLLECTOR_RUNS_TOTAL.labels(collector="dummy", status="success")._value.get()
    assert end_success == start_success + 1

    start_error = COLLECTOR_RUNS_TOTAL.labels(collector="boom", status="error")._value.get()
    with pytest.raises(RuntimeError):
        with collector_timing("boom"):
            raise RuntimeError("fail")
    end_error = COLLECTOR_RUNS_TOTAL.labels(collector="boom", status="error")._value.get()
    assert end_error == start_error + 1


@pytest.mark.asyncio
async def test_heartbeat_and_health_metrics(monkeypatch):
    # Heartbeat increment
    from pipeline.health import heartbeat, start_health_server

    stop_event = asyncio.Event()

    async def run_hb():
        # run two cycles
        task = asyncio.create_task(heartbeat(0.05, stop_event=stop_event))
        await asyncio.sleep(0.13)
        stop_event.set()
        with suppress(Exception):
            await task

    before = HEARTBEAT_TICKS_TOTAL.labels(source=os.getenv("RUN_ID", "main"))._value.get()
    await run_hb()
    after = HEARTBEAT_TICKS_TOTAL.labels(source=os.getenv("RUN_ID", "main"))._value.get()
    assert after >= before + 2  # at least two ticks

    # Health requests
    server = start_health_server(0)
    assert server is not None

    import http.client
    port = server.server_address[1]
    conn = http.client.HTTPConnection("localhost", port, timeout=5)
    conn.request("GET", "/health")
    resp = conn.getresponse()
    assert resp.status == 200
    conn.close()

    conn2 = http.client.HTTPConnection("localhost", port, timeout=5)
    conn2.request("GET", "/notfound")
    resp2 = conn2.getresponse()
    assert resp2.status == 404
    conn2.close()

    # allow metrics update
    data = generate_latest()
    assert b"health_requests_total" in data
    assert b'endpoint="/health",status="200"' in data
    assert b'endpoint="/notfound",status="404"' in data

    server.shutdown()
    server.server_close()

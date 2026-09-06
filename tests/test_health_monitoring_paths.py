import asyncio
import json
import socket
import time
from contextlib import closing

import pytest

from pipeline.health import heartbeat, start_health_server
from pipeline.metrics import HEALTH_REQUESTS_TOTAL, HEARTBEAT_TICKS_TOTAL


def _free_port():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_heartbeat_increments(monkeypatch):
    ev = asyncio.Event()
    calls: dict[str, int] = {}

    def provider():
        calls["n"] = calls.get("n", 0) + 1
        return {"x": 1}

    async def run():
        task = asyncio.create_task(heartbeat(0, provider, ev))
        await asyncio.sleep(0.05)  # quelques itérations
        ev.set()
        await task

    await run()
    # provider appelé au moins 1 fois
    assert calls.get("n", 0) >= 1
    if HEARTBEAT_TICKS_TOTAL:
        # Le label 'source' correspond au RUN_ID courant (défini dans logging_config) ou à une valeur générée.
        # On inspecte toutes les séries enregistrées et vérifie qu'au moins une a été incrémentée.
        found = False
        for sample in getattr(HEARTBEAT_TICKS_TOTAL, "_metrics", {}).values():  # prometheus client internal
            # sample est un MetricWrapper -> on accède à _value
            try:
                if sample._value.get() >= 1:  # type: ignore[attr-defined]
                    found = True
                    break
            except Exception:
                pass
        assert found, "Heartbeat metric not incremented"


@pytest.mark.asyncio
async def test_health_server_ok(monkeypatch):
    # Fake scheduler snapshot provider
    class FakeSched:
        def get_jobs(self):
            class J:
                id = "job1"

            return [J()]

    # Monkeypatch scheduler.runner.get_status_snapshot
    import sys
    import types

    snap_mod = types.ModuleType("scheduler.runner")

    def get_status_snapshot():
        return {"ready": True, "ready_ts": int(time.time())}

    snap_mod.get_status_snapshot = get_status_snapshot  # type: ignore[attr-defined]
    sys.modules["scheduler.runner"] = snap_mod
    port = _free_port()
    server = start_health_server(port, scheduler_ref=FakeSched())
    assert server is not None
    import urllib.request

    data = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).read().decode()
    obj = json.loads(data)
    assert obj["ready"] is True and obj["ports"]["health"]
    # metrics/ready endpoint
    ready_txt = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics/ready", timeout=2).read().decode()
    assert "ready " in ready_txt
    if HEALTH_REQUESTS_TOTAL:
        # Count at least one 200 for /health
        found = False
        for sample in HEALTH_REQUESTS_TOTAL._samples():  # type: ignore[attr-defined]
            labels = dict(sample.labels)
            if labels.get("endpoint") == "/health" and labels.get("status") == "200":
                found = True
                break
        assert found

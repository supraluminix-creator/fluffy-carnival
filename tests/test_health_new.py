import asyncio
import sys
import types

import httpx
import pytest

from pipeline import health as hmod


def test_start_health_server_and_request(monkeypatch):
    # Patch get_status_snapshot avant de démarrer le serveur
    fake_runner = types.SimpleNamespace(get_status_snapshot=lambda: {"ready": True, "ready_ts": 123})
    sys.modules["scheduler.runner"] = fake_runner  # type: ignore
    srv = hmod.start_health_server(0)
    assert srv is not None
    port = srv.server_address[1]
    r = httpx.get(f"http://127.0.0.1:{port}/health")
    assert r.status_code == 200
    data = r.json()
    assert "ready" in data


@pytest.mark.asyncio
async def test_heartbeat_one_tick(monkeypatch):
    # Stop après une itération
    stop = asyncio.Event()
    calls = {}

    def provider():
        calls["c"] = True
        return {"extra": 1}

    async def fast_sleep(_):
        stop.set()

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    await hmod.heartbeat(0, provider=provider, stop_event=stop)
    assert "c" in calls

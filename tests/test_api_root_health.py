from __future__ import annotations

from fastapi.testclient import TestClient

from pipeline.api import app


def test_root_and_health_endpoints():
    client = TestClient(app)
    r_root = client.get("/")
    assert r_root.status_code == 200
    body = r_root.json()
    assert body.get("service")

    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    h = r_health.json()
    assert h.get("status") == "ok"
    # Champs enrichis
    assert "version" in h
    assert "git_sha" in h
    assert "build_date" in h
    assert "started_at" in h
    assert "uptime_seconds" in h

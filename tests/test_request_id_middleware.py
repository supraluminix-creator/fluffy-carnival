from __future__ import annotations

from fastapi.testclient import TestClient

from pipeline.api import app


def test_request_id_generated_if_missing():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    rid = r.headers.get("X-Request-ID")
    assert rid is not None and len(rid) >= 16


def test_request_id_echo_if_provided():
    client = TestClient(app)
    given = "abc123"
    r = client.get("/api/health", headers={"X-Request-ID": given})
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID") == given

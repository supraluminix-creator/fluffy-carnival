from __future__ import annotations

from fastapi.testclient import TestClient

from pipeline.api import app


def test_llm_status_endpoint():
    client = TestClient(app)
    r = client.get("/api/llm/status")
    assert r.status_code == 200
    body = r.json()
    assert "models" in body and isinstance(body["models"], list)
    assert any(isinstance(m.get("remaining"), int) for m in body["models"])  # at least one
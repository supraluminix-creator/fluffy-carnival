from __future__ import annotations

from fastapi.testclient import TestClient

import pipeline.api as api


def test_api_version_endpoint():
    client = TestClient(api.app)
    r = client.get("/api/version")
    assert r.status_code == 200
    data = r.json()
    assert "version" in data
    assert "git_sha" in data
    assert "build_date" in data
    assert "started_at" in data

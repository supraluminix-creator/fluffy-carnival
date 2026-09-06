from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

import pipeline.api as api_mod
from pipeline.api import app
from pipeline.rate_limit import RateLimiter


def _now_run_id():
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def test_rate_limit_report(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("API_WRITE_KEY", "k")
    # set small limit for test on the actual module attribute used by handlers
    api_mod._RATE_LIMIT = RateLimiter(limit_per_minute=2)
    payload = {"meta": {"asset": "BTC", "run_id": _now_run_id()}}
    h = {"X-API-KEY": "k"}
    r1 = client.post("/api/report", json=payload, headers=h)
    r2 = client.post("/api/report", json=payload, headers=h)
    r3 = client.post("/api/report", json=payload, headers=h)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r3.status_code == 429
    assert r3.headers.get("Retry-After") is not None


def test_rate_limit_llm(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("API_WRITE_KEY", "k")
    api_mod._RATE_LIMIT = RateLimiter(limit_per_minute=1)
    h = {"X-API-KEY": "k"}
    r1 = client.post("/api/llm/generate", json={"prompt": "hi"}, headers=h)
    r2 = client.post("/api/llm/generate", json={"prompt": "hi"}, headers=h)
    assert r1.status_code == 200
    assert r2.status_code == 429
    assert r2.headers.get("Retry-After") is not None

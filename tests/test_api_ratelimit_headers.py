from __future__ import annotations

from fastapi.testclient import TestClient

import pipeline.api as api_mod
from pipeline.api import app
from pipeline.rate_limit import RateLimiter


def test_ratelimit_headers_on_report_success(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("API_WRITE_KEY", "k")
    api_mod._RATE_LIMIT = RateLimiter(limit_per_minute=100)
    payload = {"meta": {"asset": "BTC", "run_id": "2025-09-24T00:00:00Z"}}
    r = client.post("/api/report", json=payload, headers={"X-API-KEY": "k"})
    assert r.status_code == 201
    assert r.headers.get("X-RateLimit-Limit") is not None
    assert r.headers.get("X-RateLimit-Remaining") is not None
    assert r.headers.get("X-RateLimit-Reset") is not None


def test_ratelimit_headers_on_llm_generate_success(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("API_WRITE_KEY", "k")
    api_mod._RATE_LIMIT = RateLimiter(limit_per_minute=100)
    # keep providers mocked
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    r = client.post(
        "/api/llm/generate",
        json={"prompt": "hi"},
        headers={"X-API-KEY": "k"},
    )
    assert r.status_code == 200
    assert r.headers.get("X-RateLimit-Limit") is not None
    assert r.headers.get("X-RateLimit-Remaining") is not None
    assert r.headers.get("X-RateLimit-Reset") is not None


def test_ratelimit_headers_on_llm_stream_success(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("API_WRITE_KEY", "k")
    api_mod._RATE_LIMIT = RateLimiter(limit_per_minute=100)
    # stay in mock mode
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    with client.stream(
        "POST",
        "/api/llm/stream",
        json={"prompt": "hi"},
        headers={"X-API-KEY": "k"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers.get("X-RateLimit-Limit") is not None
        assert resp.headers.get("X-RateLimit-Remaining") is not None
    assert resp.headers.get("X-RateLimit-Reset") is not None

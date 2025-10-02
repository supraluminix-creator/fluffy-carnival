from __future__ import annotations

from fastapi.testclient import TestClient

from pipeline.api import app


def test_llm_generate_requires_api_key(monkeypatch):
    client = TestClient(app)
    monkeypatch.delenv("API_WRITE_KEY", raising=False)
    r = client.post("/api/llm/generate", json={"prompt": "Hello"})
    assert r.status_code == 403


def test_llm_generate_mock_ok(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("API_WRITE_KEY", "k")
    # ensure no external provider is selected by env (keep defaults)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    r = client.post(
        "/api/llm/generate",
        json={"prompt": "Say BTC"},
        headers={"X-API-KEY": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["model"] in (None, "mock", "gpt-4o-mini", "openrouter/auto", "llama3.1")
    # by default we expect mock prefix to appear
    assert body["output"].startswith("[MOCK:")


def test_llm_generate_with_model_hint(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("API_WRITE_KEY", "k")
    r = client.post(
        "/api/llm/generate",
        json={"prompt": "Hi", "model": "mock"},
        headers={"X-API-KEY": "k"},
    )
    assert r.status_code == 200
    assert r.json()["output"].startswith("[MOCK:mock]")

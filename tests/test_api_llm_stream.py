from __future__ import annotations

from fastapi.testclient import TestClient

from pipeline.api import app


def test_llm_stream_requires_api_key(monkeypatch):
    client = TestClient(app)
    monkeypatch.delenv("API_WRITE_KEY", raising=False)
    r = client.post("/api/llm/stream", json={"prompt": "Hello"})
    assert r.status_code == 403


def test_llm_stream_ok(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("API_WRITE_KEY", "k")
    # On force les providers externes off pour rester en mock
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    with client.stream(
        "POST", 
        "/api/llm/stream", 
        json={"prompt": "STREAM BTC"}, 
        headers={"X-API-KEY": "k"}
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        chunks = list(resp.iter_lines())
        # Devrait contenir au moins 2 events (un ou plusieurs data + [DONE])
        assert any(line.startswith("data: ") for line in chunks)
        assert any("[DONE]" in line for line in chunks)

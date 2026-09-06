from fastapi.testclient import TestClient


def test_https_enforce_blocks_non_local(monkeypatch):
    # Enable HTTPS enforcement
    monkeypatch.setenv("API_ENFORCE_HTTPS", "1")
    from pipeline.api import app

    with TestClient(app) as client:
        # Simuler un accès non-local en ajustant Host (le client utilise 127.0.0.1 par défaut)
        r = client.get("/api/health", headers={"Host": "example.com"})
        assert r.status_code == 400
        assert r.json().get("detail") == "HTTPS required"


def test_https_enforce_allows_localhost(monkeypatch):
    monkeypatch.setenv("API_ENFORCE_HTTPS", "1")
    from pipeline.api import app

    with TestClient(app) as client:
        # Host localhost doit rester autorisé en HTTP
        r = client.get("/api/health", headers={"Host": "localhost"})
        assert r.status_code == 200

from __future__ import annotations

from fastapi.testclient import TestClient


def test_cors_enabled_for_origin(monkeypatch):
    monkeypatch.setenv("API_CORS_ENABLED", "1")
    monkeypatch.setenv("API_CORS_ORIGINS", "https://example.com")
    # Import after env set so middleware is applied at import time
    from importlib import reload

    import pipeline.api as api_module

    reload(api_module)
    client = TestClient(api_module.app)

    r = client.options(
        "/api/report/latest",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in (200, 204)
    # Preflight or standard response should include CORS header
    assert r.headers.get("access-control-allow-origin") in ("*", "https://example.com")

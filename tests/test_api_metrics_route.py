import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("xff, expected", [(None, 403), ("127.0.0.1", 200)])
def test_metrics_route_allowlist(monkeypatch, xff, expected):
    # Import lazily to ensure env vars are considered at request time
    from pipeline.api import app

    # Restrict strictly to localhost so default test host is rejected unless XFF provided
    monkeypatch.setenv("METRICS_ALLOWED_HOSTS", "127.0.0.1,::1,localhost")
    if xff:
        monkeypatch.setenv("METRICS_TRUST_XFF", "1")
    with TestClient(app) as client:
        headers = {"X-Request-ID": "test-metrics"}
        if xff:
            headers["X-Forwarded-For"] = xff
        r = client.get("/metrics", headers=headers)
        assert r.status_code == expected
        if expected == 200:
            # Prometheus exposition format content type typically starts with text/plain; version=0.0.4
            ct = r.headers.get("content-type", "")
            assert ct.startswith("text/plain")
            # Basic sanity: response should contain HELP/TYPE lines
            body = r.text
            assert "# HELP" in body and "# TYPE" in body

from __future__ import annotations

import os
from contextlib import contextmanager

from fastapi.testclient import TestClient

import pipeline.api as api


@contextmanager
def env(**kwargs):
    old = {k: os.environ.get(k) for k in kwargs}
    try:
        for k, v in kwargs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_security_headers_present_on_health():
    client = TestClient(api.app)
    r = client.get("/api/health")
    assert r.status_code == 200
    # X-Request-ID always present
    assert r.headers.get("X-Request-ID")
    # Basic security headers
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "no-referrer"


def test_https_enforcement_blocks_non_secure_non_localhost(monkeypatch):
    with env(API_ENFORCE_HTTPS="1"):
        # Re-import app to ensure middleware sees env? App is module-level; use client and override headers
        client = TestClient(api.app)
        r = client.get("/api/health", headers={"host": "api.example.com"})
        assert r.status_code == 400
        assert r.json().get("detail") == "HTTPS required"


def test_https_enforcement_allows_localhost(monkeypatch):
    with env(API_ENFORCE_HTTPS="1"):
        client = TestClient(api.app)
        r = client.get("/api/health", headers={"host": "127.0.0.1"})
        assert r.status_code == 200


def test_https_enforcement_respects_x_forwarded_proto(monkeypatch):
    with env(API_ENFORCE_HTTPS="1"):
        client = TestClient(api.app)
        r = client.get("/api/health", headers={"host": "api.example.com", "x-forwarded-proto": "https"})
        assert r.status_code == 200

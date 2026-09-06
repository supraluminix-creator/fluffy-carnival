from __future__ import annotations

import os
from contextlib import contextmanager

from fastapi.testclient import TestClient

import pipeline.api as api
from pipeline import db_adapter
from pipeline.schemas import Report, ReportMeta


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


def make_report(ts: str, asset: str = "BTC") -> Report:
    return Report(meta=ReportMeta(asset=asset, run_id=ts))


def test_etag_and_304_on_latest():
    db_adapter.reset_reports()
    client = TestClient(api.app)

    # Seed a simple report
    r = make_report("2025-09-25T00:00:00Z")
    db_adapter.write_report(r)

    # First fetch returns an ETag
    resp1 = client.get("/api/report/latest")
    assert resp1.status_code == 200
    etag = resp1.headers.get("ETag")
    assert etag and len(etag) > 10

    # Second fetch with If-None-Match yields 304
    resp2 = client.get("/api/report/latest", headers={"If-None-Match": etag})
    assert resp2.status_code == 304


def test_paginated_history_etag_cache_control_and_304():
    db_adapter.reset_reports()
    client = TestClient(api.app)
    # Seed 3 reports
    db_adapter.write_report(make_report("2025-09-25T00:00:00Z"))
    db_adapter.write_report(make_report("2025-09-25T01:00:00Z"))
    db_adapter.write_report(make_report("2025-09-25T02:00:00Z"))

    with env(API_READ_MAX_AGE="60"):
        r1 = client.get("/api/report/history?interval=1h&page=1&page_size=2")
        assert r1.status_code == 200
        assert r1.headers.get("ETag")
        # Cache-Control only when flag is set
        assert r1.headers.get("Cache-Control") == "public, max-age=60"

        etag = r1.headers["ETag"]
        r2 = client.get(
            "/api/report/history?interval=1h&page=1&page_size=2",
            headers={"If-None-Match": etag},
        )
        assert r2.status_code == 304


def test_body_size_limit_413_on_generate():
    client = TestClient(api.app)
    # Require API key for POST
    with env(API_WRITE_KEY="k", API_MAX_BODY_BYTES="10"):
        # prompt > 10 bytes
        data = {"prompt": "x" * 64}
        r = client.post("/api/llm/generate", json=data, headers={"X-API-KEY": "k"})
        assert r.status_code == 413


def test_sse_headers_present():
    client = TestClient(api.app)
    with (
        env(API_WRITE_KEY="k"),
        client.stream(
            "POST",
            "/api/llm/stream",
            json={"prompt": "Hello SSE"},
            headers={"X-API-KEY": "k"},
        ) as resp,
    ):
        assert resp.status_code == 200
        # SSE anti-buffering headers
        assert resp.headers.get("Cache-Control") == "no-cache"
        assert resp.headers.get("Connection") == "keep-alive"
        assert resp.headers.get("X-Accel-Buffering") == "no"

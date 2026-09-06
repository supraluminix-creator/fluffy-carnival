from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pipeline import api


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


def _write_snapshot(path: Path) -> None:
    payload = {
        "records": [
            {
                "topic": "AI tokens",
                "sentiment": "positive",
                "value": 0.72,
                "confidence": 0.81,
                "timestamp": "2025-10-26T08:00:00Z",
                "source": "rumour.app",
            },
            {
                "topic": "ETF fatigue",
                "sentiment": "negative",
                "value": -0.68,
                "confidence": 0.74,
                "timestamp": "2025-10-26T08:10:00Z",
                "source": "rumour.app",
            },
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_rumour_reports_endpoint_returns_data(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "rumour_latest.json"
    _write_snapshot(snapshot_path)
    monkeypatch.setattr(api, "_RUMOUR_SNAPSHOT_PATH", snapshot_path)

    class _LLMStub:
        def generate(self, prompt: str, **_: object) -> str:  # noqa: D401 - simple stub
            assert "rumeurs" in prompt
            return "summary"

        def quota(self):  # pragma: no cover - not used but keeps interface similar
            return None

    stub = _LLMStub()
    monkeypatch.setattr(api, "_LLM_CLIENT", stub)

    resp = client.get("/api/rumour/reports")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["summary"] == "summary"
    assert body["items"][0]["topic"] == "AI tokens"


def test_rumour_reports_endpoint_404_when_missing(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "missing.json"
    monkeypatch.setattr(api, "_RUMOUR_SNAPSHOT_PATH", snapshot_path)
    resp = client.get("/api/rumour/reports")
    assert resp.status_code == 404

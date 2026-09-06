from __future__ import annotations

from fastapi.testclient import TestClient

from pipeline.api import app
from signals import reset_predictor


def test_signals_health_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNALS_BACKLOG_PATH", str(tmp_path / "backlog"))
    monkeypatch.setenv("ML_MODEL_PATH", str(tmp_path / "model.pkl"))
    reset_predictor()

    client = TestClient(app)

    resp_api = client.get("/api/health/signals")
    assert resp_api.status_code == 200
    payload_api = resp_api.json()
    assert payload_api["status"] == "degraded"
    assert payload_api["model_loaded"] is False
    assert payload_api["backlog_size"] == 0
    assert payload_api["model_path"].endswith("model.pkl")

    resp_root = client.get("/health/signals")
    assert resp_root.status_code == 200
    payload_root = resp_root.json()
    assert payload_root == payload_api

    reset_predictor()

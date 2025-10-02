import httpx
import pytest

from pipeline import http_wrappers
from pipeline.http_wrappers import RateLimitError, http_get_json_retry
from pipeline.metrics import HTTP_RETRIES_TOTAL, HTTP_RETRY_ATTEMPT_LATENCY_SECONDS


class DummyResp:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
    def json(self):
        return self._json
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


def test_http_get_json_retry_success_after_failures(monkeypatch):
    calls = {"n": 0}
    def fake_get(url, headers=None, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            # Simule HTTP 429 -> RateLimitError
            return DummyResp(429, {"err": "rate"})
        return DummyResp(200, {"ok": True})
    monkeypatch.setattr(http_wrappers.httpx, "get", fake_get)
    data = http_get_json_retry("https://api.test/res", retries=5, backoff_base=0.01)
    assert data == {"ok": True}
    # 2 retries enregistrés
    # endpoint_label("https://api.test/res") -> "test/res" (host core + premier segment utile)
    assert HTTP_RETRIES_TOTAL.labels(endpoint="test/res", reason="RateLimitError")._value.get() == 2
    # Vérifie histogramme a au moins une observation; attempt labels 1 et 2
    # (on ne teste pas la valeur exacte, juste existence)
    # Accès interne (prometheus_client) - toléré ici car test ciblé
    # On vérifie dimension via samples
    metric = HTTP_RETRY_ATTEMPT_LATENCY_SECONDS
    samples = [s for s in metric.collect()[0].samples if s.name == 'http_retry_attempt_latency_seconds_count']
    attempts = {s.labels['attempt'] for s in samples}
    assert '1' in attempts and '2' in attempts


def test_http_get_json_retry_exhaust(monkeypatch):
    def always_429(url, headers=None, params=None, timeout=None):
        return DummyResp(429, {"err": "rate"})
    monkeypatch.setattr(http_wrappers.httpx, "get", always_429)
    with pytest.raises(RateLimitError):
        http_get_json_retry("https://api.test/res2", retries=2, backoff_base=0.01)
    # retries = 2 (attempts 1 fail immediate, attempt2 fail, attempt3 dépasse et raise)
    assert HTTP_RETRIES_TOTAL.labels(endpoint="test/res2", reason="RateLimitError")._value.get() == 2

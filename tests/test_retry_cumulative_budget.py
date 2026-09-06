import httpx
import pytest

from pipeline.errors import TimeoutError_
from pipeline.http_wrappers import http_get_json_retry


class DummyResp:
    def __init__(self, status=429):
        self.status_code = status

    def json(self):
        return {"ok": True}

    def raise_for_status(self):
        # ne lève pas; _map_status gère
        return None


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("RETRY_MAX_CUMULATIVE_SLEEP_SEC", "0.5")
    monkeypatch.setenv("RETRY_HTTP_MAX", "10")
    monkeypatch.setenv("RETRY_HTTP_ENABLED", "1")
    yield
    monkeypatch.delenv("RETRY_MAX_CUMULATIVE_SLEEP_SEC", raising=False)


def test_retry_budget_exhaustion(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, headers=None, params=None, timeout=10):
        calls["n"] += 1
        return DummyResp(status=429)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(TimeoutError_):
        http_get_json_retry("https://api.coingecko.com/api/v3/coins/bitcoin", retries=20, backoff_base=0.05)
    assert calls["n"] > 1

from typing import Any

import requests

from pipeline.collectors.defi import fetch_defillama_tvl


class DummyResp:
    def __init__(self, payload: Any, error: Exception | None = None):
        self._payload = payload
        self._error = error

    def raise_for_status(self) -> None:  # pragma: no cover
        if self._error:
            raise self._error

    def json(self):
        return self._payload


def test_defillama_tvl_success(monkeypatch):
    payload = {"tvl": 1000, "tvlPrevDay": 900, "tvlPrevWeek": 800, "tvlPrevMonth": 700}

    def fake_get(url: str, timeout: int = 10):  # noqa: D401
        return DummyResp(payload)

    monkeypatch.setattr(requests, "get", fake_get)
    rec = fetch_defillama_tvl("ethereum")
    assert rec is not None
    assert rec["tvl"] == 1000.0
    assert rec["tvl_prev_month"] == 700.0


def test_defillama_tvl_schema_invalid(monkeypatch):
    def fake_get(url: str, timeout: int = 10):
        return DummyResp([1, 2, 3])  # not a dict

    monkeypatch.setattr(requests, "get", fake_get)
    rec = fetch_defillama_tvl("ethereum")
    assert rec is None


def test_defillama_tvl_network_error(monkeypatch):
    def fake_get(url: str, timeout: int = 10):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "get", fake_get)
    rec = fetch_defillama_tvl("ethereum")
    assert rec is None

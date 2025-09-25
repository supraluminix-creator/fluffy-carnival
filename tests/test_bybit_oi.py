from typing import Any

import pytest
import requests

from pipeline.collectors.bybit_OI import BybitWSCollector


class DummyResp:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload
    def raise_for_status(self) -> None:  # pragma: no cover - no error path
        return
    def json(self) -> dict[str, Any]:
        return self._payload

@pytest.mark.parametrize("payload, expect_none", [
    ({"result": {"list": [{"symbol": "BTCUSDT", "openInterest": "12345.6", "timestamp": 1700000000000}]}}, False),
    ({"result": {"list": []}}, True),
    ({"result": {"list": [{"symbol": "BTCUSDT", "openInterest": None, "timestamp": 1700000000000}]}}, True),
    ({"bad": 1}, True),
])
def test_bybit_oi_parse(monkeypatch, payload, expect_none):
    def fake_get(url: str, timeout: int = 10):
        return DummyResp(payload)
    monkeypatch.setattr(requests, "get", fake_get)
    rec = BybitWSCollector.fetch_bybit_oi("BTCUSDT")
    if expect_none:
        assert rec is None
    else:
        assert rec is not None
        assert rec["symbol"] == "BTCUSDT"
        assert isinstance(rec["open_interest"], float)
        assert isinstance(rec["timestamp"], int)

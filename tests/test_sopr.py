from typing import Any

import pytest
import requests

from pipeline.collectors.sopr import SOPRSource, fetch_sopr


class DummyResp:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload
    def raise_for_status(self) -> None:  # pragma: no cover
        return
    def json(self) -> dict[str, Any]:
        return self._payload

@pytest.mark.parametrize(
    "source,payload,expect_none",
    [
        (SOPRSource.BGEOMETRICS, {"sopr": "1.05", "timestamp": 1700000000}, False),
        (SOPRSource.BGEOMETRICS, {"data": {"sopr": 0.98, "timestamp": 1700000001}}, False),
        (SOPRSource.BLOCKCHAIN, {"sopr": 1.2}, False),
        (SOPRSource.BLOCKCHAIN, {"bad": 1}, True),
    ],
)
def test_fetch_sopr(monkeypatch, source: SOPRSource, payload: dict[str, Any], expect_none: bool):
    def fake_get(
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 10,
    ):  # noqa: D401
        return DummyResp(payload)
    monkeypatch.setattr(requests, "get", fake_get)
    rec = fetch_sopr(symbol="BTC", source=source, api_key=None)
    if expect_none:
        assert rec is None
    else:
        assert rec is not None
        assert isinstance(rec["sopr"], float)
        assert rec["symbol"] == "BTC"
        assert rec["source"] == source
        # timestamp may be None depending on payload variant

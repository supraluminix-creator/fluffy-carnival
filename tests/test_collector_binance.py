from collections.abc import Mapping
from types import TracebackType
from typing import Any, Literal

import httpx

from pipeline.collectors.binance import fetch_binance_price


class DummyResp:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
        self.request = httpx.Request("GET", "https://api.binance.com/api/v3/ticker/price")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "err", request=self.request, response=httpx.Response(self.status_code, request=self.request)
            )

    def json(self):
        return self._json


def test_fetch_binance_price_success(monkeypatch):
    captured = {}

    class DummyClient:
        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> Literal[False]:
            return False

        def get(
            self,
            url: str,
            *,
            params: Mapping[str, Any] | None = None,
            headers: Mapping[str, str] | None = None,
            timeout: float | None = None,
            **kwargs: Any,
        ) -> DummyResp:  # noqa: ARG002
            captured["headers"] = headers
            assert params["symbol"] == "BTCUSDT"
            return DummyResp({"symbol": "BTCUSDT", "price": "27000.12"})

    rec = fetch_binance_price(symbol="BTCUSDT", client_factory=lambda: DummyClient(), api_key="KTEST")
    assert rec and rec["value"] == 27000.12
    assert captured["headers"]["X-MBX-APIKEY"] == "KTEST"


def test_fetch_binance_price_invalid_json(monkeypatch):
    class DummyClient:
        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> Literal[False]:
            return False

        def get(
            self,
            url: str,
            *,
            params: Mapping[str, Any] | None = None,
            headers: Mapping[str, str] | None = None,
            timeout: float | None = None,
            **kwargs: Any,
        ) -> DummyResp:  # noqa: ARG002
            return DummyResp({"unexpected": 1})

    rec = fetch_binance_price(symbol="ETHUSDT", client_factory=lambda: DummyClient())
    assert rec is None

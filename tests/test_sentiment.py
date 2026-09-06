from typing import Any

import httpx
import pytest

from pipeline.collectors.sentiment import fetch_fear_greed


class DummyResp:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover
        return

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.mark.asyncio
async def test_sentiment_success(monkeypatch):
    payload: dict[str, Any] = {
        "data": [
            {
                "timestamp": 1_700_000_000,
                "value": "42",
                "value_classification": "Fear",
                "time_until_update": 3600,
            }
        ]
    }

    class DummyAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, timeout: int = 10):
            return DummyResp(payload)

    monkeypatch.setattr(httpx, "AsyncClient", DummyAsyncClient)
    rec = await fetch_fear_greed()
    assert rec is not None
    assert rec["metric_name"] == "fear_greed"
    assert rec["value"]["classification"] == "Fear"


@pytest.mark.asyncio
async def test_sentiment_fallback(monkeypatch):
    # Force primary failure by returning empty data
    payload: dict[str, Any] = {"data": []}

    class DummyAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, timeout: int = 10):
            return DummyResp(payload)

    monkeypatch.setattr(httpx, "AsyncClient", DummyAsyncClient)
    rec = await fetch_fear_greed(cache_ttl=1)
    assert rec is not None
    assert rec["source"].startswith("tokenmetrics")
    assert rec["confidence_score"] == 0.5

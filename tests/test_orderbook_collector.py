from __future__ import annotations

import pytest

from pipeline.collectors import orderbook


class _DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_fetch_orderbook_summary_basic(monkeypatch):
    sample = {
        "bids": [["100", "1"], ["99.5", "2"]],
        "asks": [["100.5", "1.5"], ["101", "2"]],
    }

    async def fake_fetch_json(url, *, params=None, timeout=None, client=None):
        assert params["symbol"] == "BTCUSDT"
        assert client is not None
        return sample

    monkeypatch.setattr(orderbook, "async_fetch_json", fake_fetch_json)
    monkeypatch.setattr(orderbook.httpx, "AsyncClient", lambda: _DummyClient())

    summary = await orderbook.fetch_orderbook_summary("BTCUSDT", depth=10, top_n=2)
    assert summary is not None
    assert summary["bids_zone"]["levels"] == 2
    assert summary["asks_zone"]["levels"] == 2
    assert summary["bid_total_quote"] == pytest.approx(100 * 1 + 99.5 * 2)
    assert summary["spread_pct"] == pytest.approx((100.5 - 100) / 100.5 * 100)


@pytest.mark.asyncio
async def test_fetch_orderbook_summary_invalid(monkeypatch):
    async def fake_fetch_json(url, *, params=None, timeout=None, client=None):
        return {"bids": [], "asks": []}

    monkeypatch.setattr(orderbook, "async_fetch_json", fake_fetch_json)
    monkeypatch.setattr(orderbook.httpx, "AsyncClient", lambda: _DummyClient())

    assert await orderbook.fetch_orderbook_summary("ETHUSDT") is None

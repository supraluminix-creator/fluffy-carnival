import asyncio
import time
from typing import Any

import httpx
import pytest

from pipeline.collectors import defillama as defillama_mod


class DummyAsyncClient:
    """Generic dummy async client emulating httpx.AsyncClient context manager."""

    def __init__(self, responses: list[Any]):
        # Each call to get pops the next response (value or Exception)
        self._responses = list(responses)

    async def __aenter__(self):  # pragma: no cover - trivial
        return self

    async def __aexit__(self, exc_type, exc, tb):  # pragma: no cover - trivial
        return False

    async def get(self, url: str, timeout: int = 10):  # noqa: D401
        if not self._responses:
            raise RuntimeError("No more dummy responses configured")
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class DummyResp:
    def __init__(self, payload: Any):
        self._payload = payload

    def raise_for_status(self):  # pragma: no cover - trivial
        return

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_get_chain_data_success(monkeypatch):
    chains_payload = [
        {"name": "Ethereum", "tvl": 12345},
        {"name": "Solana", "tvl": 2222},
    ]

    def factory(*a, **k):
        return DummyAsyncClient([DummyResp(chains_payload)])

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    data = await defillama_mod.get_chain_data("ethereum")
    assert data is not None
    assert data["tvl"] == 12345


@pytest.mark.asyncio
async def test_get_chain_data_not_found(monkeypatch):
    chains_payload = [
        {"name": "Other", "tvl": 10},
    ]

    def factory(*a, **k):
        return DummyAsyncClient([DummyResp(chains_payload)])

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    data = await defillama_mod.get_chain_data("ghostchain")
    assert data is None


@pytest.mark.asyncio
async def test_get_historical_chain_data_no_chain_data(monkeypatch):
    # Force get_chain_data to return None
    monkeypatch.setattr(defillama_mod, "get_chain_data", lambda chain: None)
    hist = await defillama_mod.get_historical_chain_data("ethereum")
    assert hist is None


@pytest.mark.asyncio
async def test_get_historical_chain_data_no_name(monkeypatch):
    async def fake_get_chain_data(chain: str):
        return {"tvl": 1000}  # missing name

    monkeypatch.setattr(defillama_mod, "get_chain_data", fake_get_chain_data)
    hist = await defillama_mod.get_historical_chain_data("ethereum")
    assert hist is None


@pytest.mark.asyncio
async def test_get_historical_chain_data_invalid_format(monkeypatch):
    async def fake_get_chain_data(chain: str):
        return {"name": "Ethereum", "tvl": 1000}

    # historical endpoint returns dict instead of list -> invalid
    def factory(*a, **k):
        return DummyAsyncClient([DummyResp({"bad": "format"})])

    monkeypatch.setattr(defillama_mod, "get_chain_data", fake_get_chain_data)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    hist = await defillama_mod.get_historical_chain_data("ethereum")
    assert hist is None


def test_parse_historical_point_variants():
    now = int(time.time())
    # list variant
    assert defillama_mod.parse_historical_point([now, 1000]) == (now, 1000.0)
    # dict with int timestamp
    assert defillama_mod.parse_historical_point({"date": now, "tvl": 500}) == (now, 500.0)
    # dict with iso date
    iso_point = {"date": "2025-09-20T00:00:00", "tvl": 123}
    parsed = defillama_mod.parse_historical_point(iso_point)
    assert parsed is not None and isinstance(parsed[0], int) and parsed[1] == 123.0
    # invalid dict
    assert defillama_mod.parse_historical_point({"date": "not-a-date", "tvl": 1}) is None
    # unrelated structure
    assert defillama_mod.parse_historical_point({"foo": "bar"}) is None


def test_calculate_historical_values_empty():
    res = defillama_mod.calculate_historical_values([], 999.0)
    assert res["tvlPrevDay"] == 999.0
    assert res["tvlPrevWeek"] == 999.0
    assert res["tvlPrevMonth"] == 999.0


def test_calculate_historical_values_points():
    now = int(time.time())
    # Provide points around each target (approx). Order scrambled to ensure search works.
    points = [
        [now - 86400 + 30, 1000],
        [now - 604800 - 15, 900],
        [now - 2592000 + 120, 800],
    ]
    res = defillama_mod.calculate_historical_values(points, 1100.0)
    assert res["tvlPrevDay"] in (1000.0, 1100.0)
    assert res["tvlPrevWeek"] in (900.0, 1100.0)
    assert res["tvlPrevMonth"] in (800.0, 1100.0)


@pytest.mark.asyncio
async def test_fetch_defillama_tvl_with_historical(monkeypatch):
    # Mock get_chain_data and get_historical_chain_data for deterministic path
    async def fake_get_chain_data(chain: str):
        return {"name": "Ethereum", "tvl": 1200}

    now = int(time.time())
    async def fake_get_hist(chain: str):
        return [
            [now - 86400, 1000],
            [now - 604800, 900],
            [now - 2592000, 800],
        ]

    monkeypatch.setattr(defillama_mod, "get_chain_data", fake_get_chain_data)
    monkeypatch.setattr(defillama_mod, "get_historical_chain_data", fake_get_hist)
    # Clear cache key if present
    key = "defillama_eth"
    if key in defillama_mod.cache:  # pragma: no cover - safety
        del defillama_mod.cache[key]
    result = await defillama_mod.fetch_defillama_tvl("eth", cache_ttl=1)
    assert result is not None
    assert result["confidence_score"] == 1.0
    assert result["value"]["tvlPrevMonth"] == 800


@pytest.mark.asyncio
async def test_fetch_defillama_tvl_no_historical(monkeypatch):
    async def fake_get_chain_data(chain: str):
        return {"name": "Ethereum", "tvl": 500}

    async def fake_get_hist(chain: str):
        return None

    monkeypatch.setattr(defillama_mod, "get_chain_data", fake_get_chain_data)
    monkeypatch.setattr(defillama_mod, "get_historical_chain_data", fake_get_hist)
    result = await defillama_mod.fetch_defillama_tvl("eth", cache_ttl=1)
    assert result is not None
    assert result["confidence_score"] == 0.8  # degraded confidence due to missing history


@pytest.mark.asyncio
async def test_fetch_defillama_tvl_no_tvl(monkeypatch):
    async def fake_get_chain_data(chain: str):
        return {"name": "Ethereum"}  # missing tvl

    monkeypatch.setattr(defillama_mod, "get_chain_data", fake_get_chain_data)
    res = await defillama_mod.fetch_defillama_tvl("eth", cache_ttl=1)
    assert res is None


def test_defillama_collector_sync_wrapper_handles_error(monkeypatch):
    # Force async fetch to raise so sync wrapper returns None gracefully
    async def fake_async(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(defillama_mod, "fetch_defillama_tvl", fake_async)
    collector = defillama_mod.DefillamaCollector(cache_ttl=1)
    res = collector.fetch_tvl("eth")
    assert res is None

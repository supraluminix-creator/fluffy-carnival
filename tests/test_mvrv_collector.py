from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_mvrv_fallback_sequence(monkeypatch):
    # Enable collector
    monkeypatch.setenv("ENABLE_MVRV_COLLECTOR", "1")
    # Clear disk cache to avoid interference from prior runs
    try:
        from pipeline.collectors import mvrv as _m

        _m.cache.clear()
    except Exception:
        pass

    # Prepare fake responses: first 404, then 200 with json, then shouldn't be called
    class FakeResp:
        def __init__(self, status, payload):
            self.status_code = status
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception(f"status {self.status_code}")

        def json(self):
            return self._payload

    async def fake_get(url, headers=None, timeout=15, params=None, **kwargs):
        url_s = str(url)
        if "mvrv-zscore" in url_s and "/v1/" not in url_s:
            return FakeResp(404, {})  # first endpoint 404
        if "/v1/mvrv-zscore" in url_s:
            return FakeResp(200, {"value": 1.23, "timestamp": 1690000000})  # success here
        return FakeResp(500, {})

    # Patch httpx.AsyncClient.get
    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=fake_get)):
        from pipeline.collectors.mvrv import fetch_mvrv

        rec = await fetch_mvrv("BTC")
        assert rec is not None
        assert rec["metric_name"] == "mvrv_z_score"
        assert float(rec["value"]) == pytest.approx(1.23)


@pytest.mark.asyncio
async def test_mvrv_final_alternate_slug(monkeypatch):
    monkeypatch.setenv("ENABLE_MVRV_COLLECTOR", "1")
    # Clear disk cache to avoid interference from prior runs
    try:
        from pipeline.collectors import mvrv as _m

        _m.cache.clear()
    except Exception:
        pass

    class FakeResp:
        def __init__(self, status, payload):
            self.status_code = status
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception(f"status {self.status_code}")

        def json(self):
            return self._payload

    order = []

    async def fake_get(url, headers=None, timeout=15, params=None, **kwargs):
        url_s = str(url)
        order.append(url_s)
        if "mvrv-zscore" in url_s and "/v1/" not in url_s:
            return FakeResp(404, {})
        if "/v1/mvrv-zscore" in url_s:
            return FakeResp(404, {})
        if "/api/metrics/mvrv" in url_s or url_s.endswith("/api/mvrv"):
            return FakeResp(200, {"value": 2.34, "timestamp": 1690001111})
        return FakeResp(500, {})

    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=fake_get)):
        from pipeline.collectors.mvrv import fetch_mvrv

        rec = await fetch_mvrv("BTC")
    assert rec is not None
    assert float(rec["value"]) == pytest.approx(2.34)
    assert order[-1].endswith("/api/metrics/mvrv") or order[-1].endswith("/api/mvrv")

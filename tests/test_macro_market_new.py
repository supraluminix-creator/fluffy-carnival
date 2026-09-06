import os
from types import SimpleNamespace

import httpx
import pytest

import pipeline.collectors.market as mmod


def _make_request(url: str = "http://dummy") -> httpx.Request:
    return httpx.Request("GET", url)


def _make_response(status_code: int, request: httpx.Request | None = None) -> httpx.Response:
    req = request or _make_request()
    return httpx.Response(status_code, request=req)


class DummyResp:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self._request = _make_request()

    def json(self):
        return self._data

    def raise_for_status(self):  # pragma: no cover (exercised)
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=self._request, response=_make_response(self.status_code, self._request))


# --- fetch_market primary success ---


def test_fetch_market_primary_success(monkeypatch):
    data = {
        "market_data": {
            "current_price": {"usd": 100},
            "total_volume": {"usd": 2000},
            "market_cap": {"usd": 30000},
            "market_cap_rank": 5,
        }
    }

    def fake_get(url, timeout=10):
        assert "coingecko" in url
        return DummyResp(data)

    monkeypatch.setattr(mmod, "httpx", SimpleNamespace(get=fake_get))
    rec = mmod.fetch_market("bitcoin")
    assert rec and rec["price"] == 100 and rec["dominance"] == 5


# --- fetch_market fallback CMC ---


def test_fetch_market_fallback_cmc(monkeypatch):
    # First call (coingecko) fails -> second success
    def fake_get(url, timeout=10):
        if "coingecko" in url:
            request = _make_request(url)
            raise httpx.HTTPStatusError("cg", request=request, response=_make_response(500, request))
        # CMC path
        return DummyResp(
            {
                "data": {
                    "BITCOIN": {
                        "quote": {
                            "USD": {"price": 101, "volume_24h": 2100, "market_cap": 31000, "market_cap_dominance": 40}
                        }
                    }
                }
            }
        )

    monkeypatch.setattr(mmod, "httpx", SimpleNamespace(get=fake_get))
    rec = mmod.fetch_market("bitcoin")
    assert rec and rec["price"] == 101 and rec["dominance"] == 40


# --- fetch_macro CoinGecko success ---
@pytest.mark.asyncio
async def test_fetch_macro_primary_success(monkeypatch):
    async def fake_get(url, timeout=10):  # used for _async_http_get_json wrapper
        return DummyResp(
            {
                "market_data": {
                    "current_price": {"usd": 150},
                    "total_volume": {"usd": 5000},
                    "market_cap": {"usd": 80000},
                    "market_cap_rank": 2,
                },
                "last_updated": "ts",
            }
        )

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, timeout=10):
            return DummyResp(
                {
                    "market_data": {
                        "current_price": {"usd": 150},
                        "total_volume": {"usd": 5000},
                        "market_cap": {"usd": 80000},
                        "market_cap_rank": 2,
                    },
                    "last_updated": "ts",
                }
            )

    monkeypatch.setattr(mmod, "httpx", SimpleNamespace(AsyncClient=lambda: FakeAsyncClient(), get=mmod.httpx.get))
    res = await mmod.fetch_macro("bitcoin")
    assert res and res["value"]["price"] == 150 and res["source"] == "coingecko"


# --- fetch_macro CG fail -> spot fallback (flag) ---
@pytest.mark.asyncio
async def test_fetch_macro_spot_fallback(monkeypatch):
    os.environ["ENABLE_BINANCE_SPOT_FALLBACK"] = "1"

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, timeout=10):
            request = _make_request(url)
            raise httpx.HTTPStatusError("cg", request=request, response=_make_response(500, request))

    # Patch binance spot
    import pipeline.collectors.binance as bbin

    def fake_spot(sym):
        return {
            "timestamp": 0,
            "asset": "BTC",
            "symbol": sym,
            "metric_name": "spot_price_usdt",
            "value": 123.0,
            "source": "binance_spot",
            "confidence_score": 0.9,
        }

    monkeypatch.setattr(bbin, "fetch_binance_spot_price", fake_spot)
    monkeypatch.setattr(mmod, "fetch_binance_spot_price", fake_spot)
    monkeypatch.setattr(mmod, "httpx", SimpleNamespace(AsyncClient=lambda: FakeAsyncClient(), get=mmod.httpx.get))
    res = await mmod.fetch_macro("bitcoin")
    assert res and res["source"] == "binance_spot" and res["value"]["price"] == 123.0
    os.environ.pop("ENABLE_BINANCE_SPOT_FALLBACK", None)


# --- fetch_macro CG & spot fail -> CMC fallback success ---
@pytest.mark.asyncio
async def test_fetch_macro_cmc_fallback(monkeypatch):
    os.environ["ENABLE_BINANCE_SPOT_FALLBACK"] = "1"

    class FakeAsyncClient1:  # CG failing
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, timeout=10):
            request = _make_request(url)
            raise httpx.HTTPStatusError("cg", request=request, response=_make_response(500, request))

    class FakeAsyncClient2:  # CMC success
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, timeout=10):
            return DummyResp(
                {
                    "data": {
                        "BITCOIN": {
                            "quote": {
                                "USD": {
                                    "price": 160,
                                    "volume_24h": 6000,
                                    "market_cap": 90000,
                                    "market_cap_dominance": 55,
                                }
                            }
                        }
                    },
                    "status": {"timestamp": "t2"},
                }
            )

    # Sequence: CG then CMC
    clients = [FakeAsyncClient1(), FakeAsyncClient2()]

    def next_client():
        return clients.pop(0)

    monkeypatch.setattr(mmod, "httpx", SimpleNamespace(AsyncClient=next_client, get=mmod.httpx.get))
    # Disable binance spot actual call by patching fetch_binance_spot_price to return None
    import pipeline.collectors.binance as bbin

    monkeypatch.setattr(bbin, "fetch_binance_spot_price", lambda s: None)
    monkeypatch.setattr(mmod, "fetch_binance_spot_price", lambda s: None)
    res = await mmod.fetch_macro("bitcoin")
    assert res and res["source"] == "coinmarketcap" and res["value"]["price"] == 160
    os.environ.pop("ENABLE_BINANCE_SPOT_FALLBACK", None)


# --- fetch_macro CG/spot/CMC fail -> binance macro simple (flag) ---
@pytest.mark.asyncio
async def test_fetch_macro_binance_macro_simple(monkeypatch):
    os.environ["ENABLE_BINANCE_MACRO_FALLBACK"] = "1"

    class FailAsyncClient:  # CG then CMC both fail
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, timeout=10, headers=None, params=None):
            if "coingecko" in url or "coinmarketcap" in url:
                request = _make_request(url)
                raise httpx.HTTPStatusError("cg", request=request, response=_make_response(500, request))
            # binance macro simple
            return DummyResp({"price": 171})

    monkeypatch.setattr(mmod, "httpx", SimpleNamespace(AsyncClient=lambda: FailAsyncClient(), get=mmod.httpx.get))
    res = await mmod.fetch_macro("bitcoin")
    assert isinstance(res, dict) and "macro_price_usd" in res and res["macro_price_usd"] == 171
    os.environ.pop("ENABLE_BINANCE_MACRO_FALLBACK", None)

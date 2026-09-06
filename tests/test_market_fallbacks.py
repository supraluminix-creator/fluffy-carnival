import httpx
import pytest

from pipeline.collectors import market as market_mod


def test_market_fallback_success(monkeypatch):
    calls = []

    class Resp1:
        def raise_for_status(self):
            raise httpx.ConnectError("fail")

        def json(self):
            return {}

    cmc_payload = {
        "data": {
            "BTC": {
                "quote": {
                    "USD": {"price": 12345.0, "volume_24h": 10, "market_cap": 1_000_000, "market_cap_dominance": 55}
                }
            }
        }
    }

    class Resp2:
        def raise_for_status(self):
            return None

        def json(self):
            return cmc_payload

    def fake_get(url: str, *a, **k):
        calls.append(url)
        if "coingecko" in url:
            return Resp1()
        return Resp2()

    monkeypatch.setattr(httpx, "get", fake_get)
    res = market_mod.fetch_market("btc")
    assert res is not None and res["symbol"] == "btc"
    assert any("coingecko" in c for c in calls) and any("coinmarketcap" in c for c in calls)


@pytest.mark.asyncio
async def test_macro_fallback_skipped_no_key(monkeypatch):
    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, timeout: int = 10):
            raise httpx.ConnectError("cg down")

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: FailingClient())
    res = await market_mod.fetch_macro("eth", cmc_api_key=None, cache_ttl=1)
    assert res is None


@pytest.mark.asyncio
async def test_macro_fallback_success(monkeypatch):
    stage = {"n": 0}

    class DynClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, headers=None, timeout: int = 10):
            if "coingecko" in url:
                stage["n"] += 1
                raise httpx.ConnectError("cg fail")
            # CMC path
            return type(
                "R",
                (),
                {
                    "raise_for_status": lambda self: None,
                    "json": lambda self: {
                        "data": {
                            "ETH": {
                                "quote": {
                                    "USD": {
                                        "price": 2000,
                                        "volume_24h": 1,
                                        "market_cap": 2_000_000,
                                        "market_cap_dominance": 18,
                                    }
                                }
                            }
                        },
                        "status": {"timestamp": "2025-01-01T00:00:00Z"},
                    },
                },
            )()

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: DynClient())
    res = await market_mod.fetch_macro("eth", cmc_api_key="KEY", cache_ttl=1)
    assert res is not None and res["source"] == "coinmarketcap"

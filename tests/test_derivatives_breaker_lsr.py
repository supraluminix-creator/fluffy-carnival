from typing import Any

import httpx
import pytest

from pipeline import circuit_breaker
from pipeline.collectors import derivatives as deriv_mod


@pytest.mark.asyncio
async def test_derivatives_lsr_breaker_skip(monkeypatch):
    circuit_breaker.reset()
    class FailingClient:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return False
        async def get(self, url: str, params: dict[str, Any] | None = None, timeout: int = 10):
            raise httpx.ConnectError("boom")
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: FailingClient())
    for _ in range(3):
        r = await deriv_mod.fetch_bybit_long_short_ratio("BTCUSDT", cache_ttl=1)
        assert r is None
    # 4e appel devrait être skip (pas de nouvel accès réseau observable ici)
    r2 = await deriv_mod.fetch_bybit_long_short_ratio("BTCUSDT", cache_ttl=1)
    assert r2 is None

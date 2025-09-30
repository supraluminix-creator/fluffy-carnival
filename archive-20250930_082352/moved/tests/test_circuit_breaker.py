from typing import Any

import httpx
import pytest

from pipeline import circuit_breaker as cb
from pipeline.collectors import derivatives as deriv_mod


@pytest.mark.asyncio
async def test_circuit_breaker_derivatives(monkeypatch):
    calls: list[int] = []
    class FailingClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def get(self, url: str, params: dict[str, Any] | None = None, timeout: int = 10):
            calls.append(1)
            raise httpx.ConnectError("boom")
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: FailingClient())
    for _ in range(3):  # 3 échecs consécutifs ouvrent breaker
        r = await deriv_mod.fetch_bybit_oi("CBTC", cache_ttl=1)
        assert r is None
    pre = len(calls)
    r4 = await deriv_mod.fetch_bybit_oi("CBTC", cache_ttl=1)
    assert r4 is None
    assert len(calls) == pre  # pas de nouvel appel réseau
    # Status snapshot
    snap = cb.breaker_status('deriv_oi')
    assert snap['is_open'] in (0,1)


def test_breaker_open_halfopen_close(monkeypatch):
    name = 'unit_breaker'
    st = cb._get(name)
    st.fail_count = 0
    st.opened_at = None
    st.threshold = 2
    # 2 failures -> open
    cb.record_failure(name)
    cb.record_failure(name)
    assert cb.should_skip(name) is True
    assert st.opened_at is not None
    # advance time to half-open window end
    base_open = st.opened_at
    monkeypatch.setattr(cb, 'time', lambda: base_open + st.cooldown + 1)
    assert cb.should_skip(name) is False  # half-open allows a try
    cb.record_success(name)
    assert st.fail_count == 0 and st.opened_at is None


def test_breaker_reset_and_metrics():
    name = 'metric_breaker'
    cb.reset(name)
    st = cb._get(name)
    assert st.fail_count == 0
    cb.record_failure(name)
    # Re-fetch to ensure we look at current state instance
    st2 = cb._get(name)
    assert st2.fail_count == 1

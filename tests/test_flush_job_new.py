import pytest

from pipeline.flush_jobs import flush_bybit_liquidations


class DummyRegistry:
    def __init__(self, will_flush: bool):
        self.will_flush = will_flush
    async def flush_if_present(self):  # pragma: no cover (exercised)
        return self.will_flush


@pytest.mark.asyncio
async def test_flush_liquidations_true(monkeypatch):
    dummy = DummyRegistry(True)
    monkeypatch.setattr('pipeline.flush_jobs.liquidations_registry', dummy)
    res = await flush_bybit_liquidations()
    assert res['flushed'] is True


@pytest.mark.asyncio
async def test_flush_liquidations_false(monkeypatch):
    dummy = DummyRegistry(False)
    monkeypatch.setattr('pipeline.flush_jobs.liquidations_registry', dummy)
    res = await flush_bybit_liquidations()
    assert res['flushed'] is False

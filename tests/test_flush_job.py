import asyncio

import pytest


class DummyWriter:
    def __init__(self):
        self.flushed = 0

    async def flush(self):  # pragma: no cover - executed
        await asyncio.sleep(0)
        self.flushed += 1


@pytest.mark.asyncio
async def test_flush_job_with_writer(monkeypatch):
    from pipeline import liquidations_registry
    from pipeline.flush_jobs import flush_bybit_liquidations

    dw = DummyWriter()
    liquidations_registry.set_writer(dw)  # type: ignore[arg-type]
    result = await flush_bybit_liquidations()
    assert result == {"flushed": True}
    assert dw.flushed == 1


@pytest.mark.asyncio
async def test_flush_job_without_writer(monkeypatch):
    from pipeline import liquidations_registry
    from pipeline.flush_jobs import flush_bybit_liquidations

    # Reset global writer
    liquidations_registry.set_writer.__globals__["_writer"] = None  # type: ignore
    result = await flush_bybit_liquidations()
    assert result == {"flushed": False}

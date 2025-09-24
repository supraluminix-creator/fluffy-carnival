import asyncio
import pytest
from pipeline.orchestrator import run_fallback_chain
from prometheus_client import REGISTRY

class TierSuccess:
    def __init__(self, value, delay=0.0):
        self.value = value
        self.delay = delay
    async def __call__(self):  # pragma: no cover (exercised)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.value

class TierNone:
    def __init__(self, delay=0.0):
        self.delay = delay
    async def __call__(self):  # pragma: no cover
        if self.delay:
            await asyncio.sleep(self.delay)
        return None

class TierError:
    def __init__(self, exc: Exception, delay=0.0):
        self.exc = exc
        self.delay = delay
    async def __call__(self):  # pragma: no cover
        if self.delay:
            await asyncio.sleep(self.delay)
        raise self.exc

@pytest.mark.asyncio
async def test_fallback_chain_success_second_tier():
    tiers = [TierNone(), TierSuccess({'x': 1})]
    res = await run_fallback_chain('test_chain', tiers)
    assert res == {'x': 1}

@pytest.mark.asyncio
async def test_fallback_chain_all_fail_none():
    tiers = [TierNone(), TierNone()]
    res = await run_fallback_chain('empty_chain', tiers)
    assert res is None

@pytest.mark.asyncio
async def test_fallback_chain_exception_then_success():
    tiers = [TierError(RuntimeError('boom')), TierSuccess(42)]
    res = await run_fallback_chain('error_chain', tiers)
    assert res == 42

@pytest.mark.asyncio
async def test_fallback_chain_all_exceptions():
    tiers = [TierError(ValueError('bad1')), TierError(RuntimeError('bad2'))]
    res = await run_fallback_chain('all_error_chain', tiers)
    assert res is None

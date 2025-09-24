import asyncio
from pipeline import fallbacks


async def _ok():
    return 42


async def _fail():
    raise RuntimeError("boom")


def test_run_fallback_chain_success():
    async def run():
        steps = [("primary", _ok), ("secondary", _fail)]
        v = await fallbacks.execute_fallback_chain("testcol", steps)
        return v
    assert asyncio.run(run()) == 42


def test_run_fallback_chain_all_fail():
    async def run():
        steps = [("a", _fail), ("b", _fail)]
        return await fallbacks.execute_fallback_chain("testcol", steps)
    assert asyncio.run(run()) is None

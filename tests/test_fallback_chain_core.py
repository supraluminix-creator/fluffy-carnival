import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, Never, TypeVar

import pytest

from pipeline.orchestrator import run_fallback_chain

T = TypeVar("T")


class TierSuccess(Generic[T]):
    def __init__(self, value: T, delay: float = 0.0):
        self.value = value
        self.delay = delay

    async def __call__(self) -> T:  # pragma: no cover (exercised)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.value


class TierNone:
    def __init__(self, delay: float = 0.0):
        self.delay = delay

    async def __call__(self) -> None:  # pragma: no cover
        if self.delay:
            await asyncio.sleep(self.delay)
        return None


class TierError:
    def __init__(self, exc: Exception, delay: float = 0.0):
        self.exc = exc
        self.delay = delay

    async def __call__(self) -> Never:  # pragma: no cover
        if self.delay:
            await asyncio.sleep(self.delay)
        raise self.exc


@pytest.mark.asyncio
async def test_fallback_chain_success_second_tier():
    tiers: list[Callable[[], Awaitable[dict[str, int] | None]]] = [TierNone(), TierSuccess({"x": 1})]
    res: dict[str, int] | None = await run_fallback_chain("test_chain", tiers)
    assert res == {"x": 1}


@pytest.mark.asyncio
async def test_fallback_chain_all_fail_none():
    tiers: list[Callable[[], Awaitable[dict[str, int] | None]]] = [TierNone(), TierNone()]
    assert await run_fallback_chain("empty_chain", tiers) is None


@pytest.mark.asyncio
async def test_fallback_chain_exception_then_success():
    tiers: list[Callable[[], Awaitable[int | None]]] = [TierError(RuntimeError("boom")), TierSuccess(42)]
    res: int | None = await run_fallback_chain("error_chain", tiers)
    assert res == 42


@pytest.mark.asyncio
async def test_fallback_chain_all_exceptions():
    tiers: list[Callable[[], Awaitable[int | None]]] = [
        TierError(ValueError("bad1")),
        TierError(RuntimeError("bad2")),
    ]
    assert await run_fallback_chain("all_error_chain", tiers) is None

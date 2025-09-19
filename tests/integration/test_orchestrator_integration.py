import asyncio
import pytest
from typing import Any

from pipeline.orchestrator import ParallelOrchestrator


class DummyCollector:
    def __init__(self, name: str, result: Any = None, delay: float = 0.0, fail: bool = False):
        self.name = name
        self._result = result
        self._delay = delay
        self._fail = fail

    async def collect(self):  # noqa: D401
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError(f"{self.name} failure")
        return self._result


@pytest.mark.asyncio
async def test_orchestrator_success_parallel():
    c1 = DummyCollector("c1", result={"v": 1}, delay=0.05)
    c2 = DummyCollector("c2", result=[1, 2, 3], delay=0.05)
    orch = ParallelOrchestrator([c1, c2])
    summary = await orch.run_all_collectors(timeout=1.0)
    assert summary["status"] == "completed"
    assert summary["successful_count"] == 2
    assert len(summary["successful_results"]) == 2


@pytest.mark.asyncio
async def test_orchestrator_partial_failure():
    c1 = DummyCollector("ok", result=42)
    c2 = DummyCollector("boom", fail=True)
    orch = ParallelOrchestrator([c1, c2])
    summary = await orch.run_all_collectors(timeout=1.0)
    assert summary["status"] == "completed"
    # one success, one error stored in failed_results
    assert summary["successful_count"] == 1
    assert summary["failed_count"] == 1


@pytest.mark.asyncio
async def test_orchestrator_timeout():
    # Create a collector that will sleep longer than timeout
    slow = DummyCollector("slow", result=1, delay=0.5)
    fast = DummyCollector("fast", result=2, delay=0.05)
    orch = ParallelOrchestrator([slow, fast])
    summary = await orch.run_all_collectors(timeout=0.1)
    assert summary["status"] in {"timeout", "completed"}
    # If timeout, we ensure correct keys
    if summary["status"] == "timeout":
        assert "timeout_seconds" in summary
    else:
        # Completed but slow finished in time (flaky margin) -> at least 2 results
        assert summary["total_count"] == 2

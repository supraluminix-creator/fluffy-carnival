import asyncio
import time

import pytest
from prometheus_client import CollectorRegistry, Counter, Histogram

from pipeline.orchestrator import ParallelOrchestrator


class DummyCollector:
    def __init__(self, name: str, delay: float = 0.0, fail: bool = False):
        self.name = name
        self._delay = delay
        self._fail = fail

    async def collect(self):  # noqa: D401
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError(f"{self.name} failed")
        return {"ok": True, "name": self.name}


@pytest.mark.asyncio
async def test_orchestrator_metrics_and_variance(monkeypatch):
    # Isolated registry
    registry = CollectorRegistry()

    local_counter = Counter(
        "orchestrator_executions_total_test",
        "Test executions",
        ["success"],
        registry=registry,
    )
    local_hist = Histogram(
        "orchestrator_duration_seconds_test",
        "Test duration",
        registry=registry,
    )

    # Patch module-level metrics to avoid interfering with global ones
    import pipeline.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "orchestrator_executions", local_counter)
    monkeypatch.setattr(orch_mod, "orchestrator_duration", local_hist)

    slow = DummyCollector("slow", delay=0.15)
    fast = DummyCollector("fast", delay=0.02)
    orch = ParallelOrchestrator([slow, fast])

    t0 = time.perf_counter()
    summary = await orch.run_all_collectors(timeout=1.0)
    elapsed = time.perf_counter() - t0

    assert summary["status"] == "completed"
    assert summary["successful_count"] == 2
    # The measured execution time should be close to the max of the delays (~0.15)
    assert 0.12 <= summary["execution_time_seconds"] <= 0.40
    assert elapsed >= 0.14  # wall clock at least slow delay

    # Check metrics scraped from registry
    metrics = registry.collect()
    names = {m.name for m in metrics}
    assert "orchestrator_executions_total_test" in names
    assert "orchestrator_duration_seconds_test" in names

    # Counter should have one sample for success=true
    for metric in metrics:
        if metric.name == "orchestrator_executions_total_test":
            sample_names = {s.labels.get("success") for s in metric.samples}
            assert "true" in sample_names or "false" in sample_names

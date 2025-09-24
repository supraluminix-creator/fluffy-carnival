import asyncio
import statistics
import time
from typing import List
from pipeline.orchestrator import ParallelOrchestrator

class SleepCollector:
    def __init__(self, name: str, delay: float):
        self.name = name
        self._delay = delay
    async def collect(self):  # simulate variable latency
        await asyncio.sleep(self._delay)
        return {"delay": self._delay}

async def _run_once(orchestrator: ParallelOrchestrator):
    start = time.perf_counter()
    await orchestrator.run_all_collectors()
    return time.perf_counter() - start

def test_orchestrator_stress_latency_distribution():
    # Build 25 collectors with spread delays 0.005 à 0.06
    delays = [0.005 + (i % 10) * 0.005 for i in range(25)]
    collectors = [SleepCollector(f"c{i}", d) for i, d in enumerate(delays)]
    orch = ParallelOrchestrator(collectors)

    async def run_n(n: int) -> List[float]:
        return [await _run_once(orch) for _ in range(n)]

    durations = asyncio.run(run_n(8))  # 8 exécutions pour stats simples
    assert len(durations) == 8
    mean = statistics.mean(durations)
    p95 = sorted(durations)[int(len(durations)*0.95)-1]
    # Critère: p95 ne dépasse pas 3x la moyenne (dispersion raisonnable)
    assert p95 <= mean * 3, f"p95 {p95:.4f}s > 3x mean {mean:.4f}s"

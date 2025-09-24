import asyncio
from pipeline.scheduler import CryptoScheduler, get_collector_intervals_from_env

class DummyCollector:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0
    async def collect(self):  # pragma: no cover (execution path validated indirectly)
        self.calls += 1
        return {"ok": True}

async def _start_short(sched: CryptoScheduler):
    await sched.start()
    await asyncio.sleep(0.01)  # very short loop
    await sched.shutdown(wait=False)


def test_scheduler_add_and_info(monkeypatch):
    sched = CryptoScheduler(jitter_percent=0)
    c = DummyCollector("demo")
    sched.add_collector(c, interval_seconds=60)  # min enforced 60
    info = sched.get_scheduler_info()
    assert info["job_count"] == 1
    assert "demo" in info["collectors"]


def test_env_intervals(monkeypatch):
    monkeypatch.setenv('COLLECTOR_INTERVAL_MARKET', '120')
    intervals = get_collector_intervals_from_env()
    assert intervals['market'] == 120

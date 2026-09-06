import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import pipeline.scheduler as scheduler_mod
from pipeline.scheduler import CryptoScheduler, get_collector_intervals_from_env


class FakeIntervalTrigger:
    def __init__(self, seconds: float):
        self.seconds = seconds

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"interval[{self.seconds}]"


class FakeScheduler:
    def __init__(self):
        self.jobs: list[SimpleNamespace] = []
        self.listeners: list[tuple] = []
        self.started = False
        self.shutdown_calls: list[bool] = []

    def add_listener(self, callback, event):
        self.listeners.append((callback, event))

    def add_job(self, func, args, trigger, id, max_instances, coalesce, misfire_grace_time):
        job = SimpleNamespace(
            func=func,
            args=args,
            trigger=trigger,
            id=id,
            next_run_time=datetime.fromtimestamp(1_700_000_000, tz=UTC),
        )
        self.jobs.append(job)
        return job

    def get_jobs(self):
        return list(self.jobs)

    def start(self):
        self.started = True

    def shutdown(self, wait=True):
        self.started = False
        self.shutdown_calls.append(wait)


class DummyCollector:
    def __init__(self, name: str, result=None, error: Exception | None = None, delay: float = 0.0):
        self.name = name
        self._result = result
        self._error = error
        self.delay = delay

    async def collect(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self._error:
            raise self._error
        return self._result


@contextmanager
def _noop_timer(_name: str):
    yield


@pytest.mark.asyncio
async def test_scheduler_add_start_and_shutdown(monkeypatch):
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_mod, "AsyncIOScheduler", lambda: fake_scheduler)
    monkeypatch.setattr(scheduler_mod, "IntervalTrigger", lambda seconds: FakeIntervalTrigger(seconds))
    monkeypatch.setattr(scheduler_mod.random, "uniform", lambda a, b: 0)
    monkeypatch.setattr(scheduler_mod, "collector_timing", _noop_timer)

    captured_signals: dict[int, object] = {}

    def fake_signal(sig, handler):
        captured_signals[sig] = handler

    monkeypatch.setattr(scheduler_mod.signal, "signal", fake_signal)

    scheduler = CryptoScheduler(jitter_percent=10)
    collector = DummyCollector("btc", result={"price": 1})
    scheduler.add_collector(collector, interval_seconds=120)

    assert "btc" in scheduler.collectors
    assert len(fake_scheduler.jobs) == 1
    assert isinstance(fake_scheduler.jobs[0].trigger, FakeIntervalTrigger)
    assert fake_scheduler.jobs[0].trigger.seconds == 120

    await scheduler.start()
    assert scheduler.running is True
    assert fake_scheduler.started is True
    assert captured_signals  # handlers registered

    info = scheduler.get_scheduler_info()
    assert info["running"] is True
    assert info["job_count"] == 1
    assert info["collectors"] == ["btc"]
    assert info["jobs"][0]["id"] == fake_scheduler.jobs[0].id
    assert info["jobs"][0]["next_run"].endswith("+00:00")

    await scheduler._safe_collect(collector)

    failing = DummyCollector("err", error=RuntimeError("boom"))
    await scheduler._safe_collect(failing)  # should not raise

    await scheduler.shutdown(wait=False)
    assert scheduler.running is False
    assert fake_scheduler.shutdown_calls == [False]


def test_get_collector_intervals_from_env(monkeypatch):
    monkeypatch.setenv("COLLECTOR_INTERVAL_MARKET", "120")
    monkeypatch.setenv("COLLECTOR_INTERVAL_DEFILLAMA", "600")
    monkeypatch.setenv("COLLECTOR_INTERVAL_ONCHAIN", "900")
    monkeypatch.setenv("COLLECTOR_INTERVAL_DERIVATIVES", "180")
    monkeypatch.setenv("COLLECTOR_INTERVAL_SENTIMENT", "240")

    intervals = get_collector_intervals_from_env()
    assert intervals == {
        "market": 120,
        "defillama": 600,
        "onchain": 900,
        "derivatives": 180,
        "sentiment": 240,
    }

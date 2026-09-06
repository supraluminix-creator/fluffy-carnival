import asyncio

import pytest

from pipeline.scheduler import CryptoScheduler


class DummyCollector:
    def __init__(self, name: str, result=None, fail: bool = False, delay: float = 0.01):
        self.name = name
        self._result = result or {"v": 1}
        self._fail = fail
        self._delay = delay

    async def collect(self):  # noqa: D401
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("boom")
        return self._result


@pytest.mark.asyncio
async def test_scheduler_add_and_info(monkeypatch):
    sched = CryptoScheduler(jitter_percent=0)  # pas de jitter pour déterminisme

    # Monkeypatch random.uniform pour vérifier chemin jitter
    import random as _random

    monkeypatch.setattr(_random, "uniform", lambda a, b: 0)

    c1 = DummyCollector("alpha")
    sched.add_collector(c1, interval_seconds=60)
    info = sched.get_scheduler_info()
    assert info["job_count"] == 1
    assert "alpha" in info["collectors"]

    # Start puis second start -> warning branch
    await sched.start()
    await sched.start()  # ne doit pas lever

    # Laisser tourner une itération
    await asyncio.sleep(0.05)
    await sched.shutdown()
    assert sched.running is False


@pytest.mark.asyncio
async def test_scheduler_job_callbacks(monkeypatch):
    # On va invoquer directement les callbacks internes pour couvrir _job_executed / _job_error
    sched = CryptoScheduler()

    class Ev:  # objet simulant event apscheduler
        def __init__(self, job_id: str, ok: bool):
            import datetime

            self.job_id = job_id
            # Utilise datetime.now(datetime.UTC) pour éviter DeprecationWarning
            self.scheduled_run_time = datetime.datetime.now(datetime.UTC)
            if not ok:
                self.exception = RuntimeError("x")
                self.traceback = "trace"

    # success path
    sched._job_executed(Ev("job1", True))
    # error path
    sched._job_error(Ev("job2", False))

    # shutdown sans start -> warning branch
    await sched.shutdown()


@pytest.mark.asyncio
async def test_scheduler_collect_error_path(monkeypatch):
    # Vérifie chemin d'erreur dans _safe_collect
    sched = CryptoScheduler()
    bad = DummyCollector("bad", fail=True)
    await sched._safe_collect(bad)  # ne lève pas (erreur loggée seulement)

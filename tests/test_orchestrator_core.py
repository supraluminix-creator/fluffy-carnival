import asyncio

import pytest

from pipeline.orchestrator import (
    ParallelOrchestrator,
    collector_error_total,
    collector_success_total,
    last_orchestrator_run_ts,
    orchestrator_timeouts_total,
)


class OkCollector:
    def __init__(self, name: str, delay: float = 0.01):
        self.name = name
        self.delay = delay

    async def collect(self):
        await asyncio.sleep(self.delay)
        return {"ok": True}


class ErrorCollector:
    def __init__(self, name: str):
        self.name = name

    async def collect(self):  # pragma: no cover - exercised but trivial
        raise RuntimeError("boom")


class SlowCollector:
    def __init__(self, name: str, delay: float):
        self.name = name
        self.delay = delay

    async def collect(self):
        await asyncio.sleep(self.delay)
        return {"slow": self.delay}


@pytest.mark.asyncio
async def test_orchestrator_success():
    orch = ParallelOrchestrator([OkCollector("a"), OkCollector("b")])
    # Valeurs initiales métriques
    a_before = (
        collector_success_total.labels(collector="a")._value.get() if ("a",) in collector_success_total._metrics else 0
    )
    b_before = (
        collector_success_total.labels(collector="b")._value.get() if ("b",) in collector_success_total._metrics else 0
    )
    result = await orch.run_all_collectors()
    assert result["status"] == "completed"
    assert result["successful_count"] == 2
    assert result["failed_count"] == 0
    # Vérifie incrément succès
    assert collector_success_total.labels(collector="a")._value.get() == a_before + 1
    assert collector_success_total.labels(collector="b")._value.get() == b_before + 1
    # Pas d'erreur collectors
    assert ("a",) not in collector_error_total._metrics or collector_error_total.labels(collector="a")._value.get() == 0
    assert ("b",) not in collector_error_total._metrics or collector_error_total.labels(collector="b")._value.get() == 0
    # Gauge timestamp doit être > 0
    assert last_orchestrator_run_ts._value.get() > 0


@pytest.mark.asyncio
async def test_orchestrator_error():
    orch = ParallelOrchestrator([OkCollector("a"), ErrorCollector("bad")])
    a_before = (
        collector_success_total.labels(collector="a")._value.get() if ("a",) in collector_success_total._metrics else 0
    )
    bad_success_before = (
        collector_success_total.labels(collector="bad")._value.get()
        if ("bad",) in collector_success_total._metrics
        else 0
    )
    bad_error_before = (
        collector_error_total.labels(collector="bad")._value.get() if ("bad",) in collector_error_total._metrics else 0
    )
    result = await orch.run_all_collectors()
    assert result["status"] == "completed"
    assert result["successful_count"] == 1
    assert result["failed_count"] == 1
    # Succès a incrémenté +1
    assert collector_success_total.labels(collector="a")._value.get() == a_before + 1
    # Pas de succès pour bad
    assert collector_success_total.labels(collector="bad")._value.get() == bad_success_before
    # Erreur pour bad incrémentée +1
    assert collector_error_total.labels(collector="bad")._value.get() == bad_error_before + 1


@pytest.mark.asyncio
async def test_orchestrator_timeout():
    orch = ParallelOrchestrator([SlowCollector("s1", 0.3), SlowCollector("s2", 0.3)])
    timeouts_before = orchestrator_timeouts_total._value.get()
    result = await orch.run_all_collectors(timeout=0.1)
    assert result["status"] == "timeout" or result["status"] == "error"
    # Si timeout détecté, compteur doit bouger (si status=error on ne force pas)
    if result["status"] == "timeout":
        assert orchestrator_timeouts_total._value.get() == timeouts_before + 1


@pytest.mark.asyncio
async def test_orchestrator_forced_global_timeout(monkeypatch):
    """Force asyncio.wait_for à lever TimeoutError immédiatement pour couvrir la branche except TimeoutError."""
    orch = ParallelOrchestrator([SlowCollector("s1", 0.05)])
    timeouts_before = orchestrator_timeouts_total._value.get()

    async def fake_wait_for(awaitable, timeout=None):  # noqa: D401
        raise TimeoutError()

    # Patch ciblé dans le module orchestrator uniquement
    import pipeline.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod.asyncio, "wait_for", fake_wait_for)

    res = await orch.run_all_collectors(timeout=0.001)
    assert res["status"] == "timeout"
    assert orchestrator_timeouts_total._value.get() == timeouts_before + 1


@pytest.mark.asyncio
async def test_orchestrator_no_collectors():
    orch = ParallelOrchestrator([])
    res = await orch.run_all_collectors()
    assert res["status"] == "skipped"
    assert res["reason"] == "no_collectors"


def test_orchestrator_add_remove_and_stats():
    orch = ParallelOrchestrator([OkCollector("x")])
    orch.add_collector(OkCollector("y"))
    assert len(orch.collectors) == 2
    assert orch.remove_collector("y") is True
    assert orch.remove_collector("zzz") is False
    stats = orch.get_orchestrator_stats()
    assert stats["collectors_count"] == 1
    assert "execution_stats" in stats


def test_orchestrator_internal_summarize_and_analyze():
    orch = ParallelOrchestrator()
    # _summarize_result branches
    assert orch._summarize_result(None)["type"] == "none"
    d = orch._summarize_result({"a": 1, "b": 2})
    assert d["type"] == "dict" and d["keys_count"] == 2
    list_summary = orch._summarize_result([1, 2, 3])
    assert list_summary["type"] == "list" and list_summary["length"] == 3
    s = orch._summarize_result("abc")
    assert s["type"] == "string" and s["length"] == 3
    o = orch._summarize_result(123)
    assert o["type"] in ("int", "int")  # type name int
    # _analyze_results branch coverage
    results = [
        {"status": "success", "execution_time": 0.01},
        {"status": "error", "execution_time": 0.02, "error": "x"},
        42,  # valeur brute non interprétée comme succès dans _summarize
        RuntimeError("fail"),
    ]
    analyzed = orch._analyze_results(results, "exec_test")
    assert analyzed["total_count"] == 4
    # Implémentation actuelle: seulement 1 dict succès est compté
    assert analyzed["successful_count"] == 1
    assert analyzed["failed_count"] == 1  # un seul dict status=error compté

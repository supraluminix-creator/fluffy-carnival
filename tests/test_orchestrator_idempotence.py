import asyncio
import os
import pytest
from prometheus_client import CollectorRegistry, Counter, Histogram
from pipeline.orchestrator import ParallelOrchestrator

class DummyCollector:
    def __init__(self, name: str, value: int):
        self.name = name
        self._value = value
    async def collect(self):
        # Simule un travail asynchrone léger
        await asyncio.sleep(0.01)
        return {"value": self._value}


@pytest.mark.skipif(os.environ.get("STRICT_COVERAGE") == "1", reason="Test isolé non conçu pour satisfaire seuil global seul")
def test_orchestrator_metrics_idempotence(monkeypatch):
    """Le fait d'exécuter deux fois l'orchestrateur ne doit pas dupliquer des compteurs hors exécutions incrémentées.

    Invariant minimal vérifié:
    - orchestrator_executions_total{success="true"} == 2 (toutes exécutions OK)
    - orchestrator_duration_seconds compte 2 observations (implicit via sum/count > 0)
    On ne réinitialise pas le registre global; on isole via un nouveau registre pour éviter contamination.
    """
    # Créer un registre isolé pour patcher les métriques globales
    registry = CollectorRegistry()

    # Re-créer métriques locales attachées au registre isolé
    orch_exec = Counter(
        'orchestrator_executions_total',
        'Total orchestrator executions',
        ['success'],
        registry=registry
    )
    orch_dur = Histogram(
        'orchestrator_duration_seconds',
        'Orchestrator execution duration',
        registry=registry
    )

    import pipeline.orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, 'orchestrator_executions', orch_exec, raising=True)
    monkeypatch.setattr(orch_mod, 'orchestrator_duration', orch_dur, raising=True)

    collectors = [DummyCollector("c1", 1), DummyCollector("c2", 2)]
    orchestrator = ParallelOrchestrator(collectors)

    async def run_twice():
        r1 = await orchestrator.run_all_collectors()
        r2 = await orchestrator.run_all_collectors()
        return r1, r2

    r1, r2 = asyncio.run(run_twice())
    assert r1['status'] == 'completed' and r2['status'] == 'completed'
    # Vérifier compteur success==2
    val_success = registry.get_sample_value('orchestrator_executions_total', {'success': 'true'})
    assert val_success == 2.0, f"Executions attendues 2, obtenu {val_success}"
    # Histogram count == 2
    count = registry.get_sample_value('orchestrator_duration_seconds_count')
    assert count == 2.0, f"Observations histogram attendues 2, obtenu {count}"

import pytest


class NullCollector:
    name = "null_collector"

    async def collect(self):  # pragma: no cover - executed
        return None


@pytest.mark.asyncio
async def test_orchestrator_null_results_non_strict():
    from pipeline.orchestrator import ParallelOrchestrator

    orch = ParallelOrchestrator(collectors=[NullCollector()], strict_none_error=False)
    res = await orch.run_all_collectors()
    assert res["status"] == "completed"
    assert res["successful_count"] == 1  # considéré success car non strict


@pytest.mark.asyncio
async def test_orchestrator_null_results_strict():
    from pipeline.orchestrator import ParallelOrchestrator

    orch = ParallelOrchestrator(collectors=[NullCollector()], strict_none_error=True)
    res = await orch.run_all_collectors()
    # En mode strict, l'unique collector est une erreur, donc 0 success
    assert res["successful_count"] == 0

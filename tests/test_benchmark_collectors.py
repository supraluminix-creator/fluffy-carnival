import json
import types
import asyncio
from pathlib import Path

from tools import benchmark_collectors as bc


async def _fast():
    return 1


async def _slow():
    await asyncio.sleep(0.01)
    return 2


def test_benchmark_structure(tmp_path, monkeypatch):
    # Remplace le registre par deux stubs déterministes
    monkeypatch.setattr(bc, "COLLECTOR_REGISTRY", {"fast": _fast, "slow": _slow})
    args = types.SimpleNamespace(
        collectors="fast,slow",
        iterations=3,
        timeout=1.0,
        json_out=str(tmp_path / "bench.json"),
        table=False,
    )
    asyncio.run(bc.main_async(args))
    data = json.loads((tmp_path / "bench.json").read_text(encoding="utf-8"))
    assert len(data) == 2
    names = {d["collector"] for d in data}
    assert names == {"fast", "slow"}
    for d in data:
        assert d["iterations"] == 3
        assert 0 <= d["success_rate"] <= 1
        assert d["p95_latency"] >= 0
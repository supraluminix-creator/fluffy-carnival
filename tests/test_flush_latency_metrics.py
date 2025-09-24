import asyncio
import sqlite3
from prometheus_client import REGISTRY
from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter


def _get_samples(name: str):
    m = REGISTRY._names_to_collectors.get(name)
    if not m:
        return []
    res = []
    for fam in m.collect():
        for s in fam.samples:
            res.append(s)
    return res


def test_flush_latency_success(tmp_path, monkeypatch):
    db_path = tmp_path / 'x.db'
    writer = BybitLiquidationsWriter(db=str(db_path), parquet_dir=str(tmp_path/'pq'), flush_size=2, parquet_enabled=False)
    events = [
        {"symbol":"BTCUSDT","side":"Buy","price":10000,"size":1,"updatedTime":1700000000000},
        {"symbol":"BTCUSDT","side":"Buy","price":10010,"size":2,"updatedTime":1700000005000},
    ]
    async def push():
        for ev in events:
            await writer.write_record(ev)
        await writer.flush()
    asyncio.run(push())
    samples = _get_samples('writer_flush_latency_seconds')
    assert any(s.labels.get('writer')=='bybit_liq' and s.labels.get('status')=='success' for s in samples)


def test_flush_latency_failure(tmp_path, monkeypatch):
    db_path = tmp_path / 'y.db'
    writer = BybitLiquidationsWriter(db=str(db_path), parquet_dir=str(tmp_path/'pq'), flush_size=1, parquet_enabled=True)

    class Boom(Exception):
        pass

    # Patch DataFrame.to_parquet pour déclencher une exception après le commit DB
    import pandas as _pd
    orig_to_parquet = _pd.DataFrame.to_parquet
    def boom(self, *a, **k):
        raise Boom('parquet fail')
    monkeypatch.setattr(_pd.DataFrame, 'to_parquet', boom)

    async def push():
        await writer.write_record({"symbol":"BTCUSDT","side":"Sell","price":10100,"size":1,"updatedTime":1700000100000})
        await writer.flush()
    asyncio.run(push())
    failure_samples = _get_samples('flush_failures_total')
    assert any(s.labels.get('writer')=='bybit_liq' and s.labels.get('phase')=='write' and s.value>=1 for s in failure_samples)
    latency_samples = _get_samples('writer_flush_latency_seconds')
    assert any(s.labels.get('writer')=='bybit_liq' and s.labels.get('status')=='error' for s in latency_samples)
    # Restore (cleanup explicit, even if monkeypatch undoes later)
    monkeypatch.setattr(_pd.DataFrame, 'to_parquet', orig_to_parquet)

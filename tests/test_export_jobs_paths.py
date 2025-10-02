import os
import pathlib
import tempfile
from contextlib import suppress

import pytest

import pipeline.export_job as ej
import pipeline.export_utils as eu
from pipeline.metrics import EXPORT_ROWS_TOTAL, EXPORTS_TOTAL

# Monkeypatch open & csv writer for deterministic writes

@pytest.fixture
def tmpdir_fs(monkeypatch):
    orig = pathlib.Path.cwd()
    with tempfile.TemporaryDirectory() as d:
        dpath = pathlib.Path(d)
        monkeypatch.chdir(d)
        try:
            yield dpath
        finally:
            with suppress(Exception):
                os.chdir(orig)

@pytest.mark.asyncio
async def test_perform_export_batch_success(monkeypatch, tmpdir_fs):
    # Patch each collector used inside perform_export_batch to return deterministic data
    def rec(name, val):
        return {"metric_name": name, "value": val, "timestamp": 1, "symbol": "X"}
    monkeypatch.setattr(ej, 'fetch_macro', lambda s, cmc_api_key=None: rec('macro', 1))
    monkeypatch.setattr(ej, 'fetch_txcount', lambda *a, **k: rec('txcount', 2))
    monkeypatch.setattr(ej, 'fetch_hashrate', lambda *a, **k: rec('hashrate', 3))
    monkeypatch.setattr(ej, 'fetch_sopr', lambda *a, **k: rec('sopr', 4))
    async def fake_oi(*a, **k): return rec('bybit_oi', 5)
    async def fake_lsr(*a, **k): return rec('bybit_lsr', 6)
    async def fake_defi(*a, **k): return rec('defillama', 7)
    async def fake_sent(*a, **k): return rec('sentiment', 8)
    monkeypatch.setattr(ej, 'fetch_bybit_oi', fake_oi)
    monkeypatch.setattr(ej, 'fetch_bybit_long_short_ratio', fake_lsr)
    monkeypatch.setattr(ej, 'fetch_defillama_tvl', fake_defi)
    monkeypatch.setattr(ej, 'fetch_fear_greed', fake_sent)
    # Run
    summary = await ej.perform_export_batch('bitcoin')
    assert summary['records'] == 8
    latest = summary['latest']
    # Fichiers écrits dans sous-dossier exports/
    assert latest and (tmpdir_fs / 'exports' / 'latest_export.csv').exists()
    # Metrics
    assert EXPORTS_TOTAL.labels(status='success')._value.get() >= 1
    assert EXPORT_ROWS_TOTAL.labels(status='success')._value.get() >= 8

@pytest.mark.asyncio
async def test_perform_export_batch_no_data(monkeypatch, tmpdir_fs):
    # Tous collectors renvoient None
    monkeypatch.setattr(ej, 'fetch_macro', lambda *a, **k: None)
    monkeypatch.setattr(ej, 'fetch_txcount', lambda *a, **k: None)
    monkeypatch.setattr(ej, 'fetch_hashrate', lambda *a, **k: None)
    monkeypatch.setattr(ej, 'fetch_sopr', lambda *a, **k: None)
    async def none_async(*a, **k): return None
    monkeypatch.setattr(ej, 'fetch_bybit_oi', none_async)
    monkeypatch.setattr(ej, 'fetch_bybit_long_short_ratio', none_async)
    monkeypatch.setattr(ej, 'fetch_defillama_tvl', none_async)
    monkeypatch.setattr(ej, 'fetch_fear_greed', none_async)
    with pytest.raises(RuntimeError):
        await ej.perform_export_batch('bitcoin')


def test_export_utils_timestamped(monkeypatch, tmpdir_fs):
    rows = [
        {"metric_name": "m", "value": 10, "timestamp": 111, "symbol": "Y"},
    ]
    eu.export_latest_and_timestamped(rows)
    assert (tmpdir_fs / 'exports' / 'latest_export.csv').exists()
    ts_files = list((tmpdir_fs / 'exports').glob('pipeline_export_*.csv'))
    assert len(ts_files) == 1

from pathlib import Path

import pytest

import pipeline.export_job as ej


@pytest.mark.asyncio
async def test_perform_export_batch_success(tmp_path, monkeypatch):
    # Patch all collectors referenced in export_job to return minimal dicts
    def ok(name):
        return {"timestamp": 1, "asset": name, "symbol": name, "chain": None, "metric_name": name, "value": 1, "source": "test", "confidence_score": 1.0}

    monkeypatch.setattr(ej, 'fetch_macro', lambda symbol, cmc_api_key=None: {"timestamp": 1, "asset": symbol, "metric_name": "macro", "value": {"price":1}, "source": "macro", "confidence_score":1.0})
    monkeypatch.setattr(ej, 'fetch_txcount', lambda *a, **k: ok('txcount'))
    monkeypatch.setattr(ej, 'fetch_hashrate', lambda *a, **k: ok('hashrate'))
    monkeypatch.setattr(ej, 'fetch_sopr', lambda *a, **k: ok('sopr'))
    monkeypatch.setattr(ej, 'fetch_bybit_oi', lambda *a, **k: ok('bybit_oi'))
    monkeypatch.setattr(ej, 'fetch_bybit_long_short_ratio', lambda *a, **k: ok('bybit_lsr'))
    monkeypatch.setattr(ej, 'fetch_defillama_tvl', lambda *a, **k: ok('defillama'))
    monkeypatch.setattr(ej, 'fetch_fear_greed', lambda *a, **k: ok('sentiment'))

    out_dir = tmp_path / "exports"
    monkeypatch.setenv('EXPORT_DIR', str(out_dir))
    monkeypatch.setenv('RUN_ID', 'TST')
    res = await ej.perform_export_batch('bitcoin')
    assert res['records'] >= 5
    # Deux fichiers (latest + timestamped) créés
    assert Path(res['latest']).exists()
    assert Path(res['timestamped']).exists()


@pytest.mark.asyncio
async def test_perform_export_batch_no_data(tmp_path, monkeypatch):
    # Tous collectors retournent None -> RuntimeError
    monkeypatch.setattr(ej, 'fetch_macro', lambda *a, **k: None)
    monkeypatch.setattr(ej, 'fetch_txcount', lambda *a, **k: None)
    monkeypatch.setattr(ej, 'fetch_hashrate', lambda *a, **k: None)
    monkeypatch.setattr(ej, 'fetch_sopr', lambda *a, **k: None)
    monkeypatch.setattr(ej, 'fetch_bybit_oi', lambda *a, **k: None)
    monkeypatch.setattr(ej, 'fetch_bybit_long_short_ratio', lambda *a, **k: None)
    monkeypatch.setattr(ej, 'fetch_defillama_tvl', lambda *a, **k: None)
    monkeypatch.setattr(ej, 'fetch_fear_greed', lambda *a, **k: None)
    monkeypatch.setenv('EXPORT_DIR', str(tmp_path / 'exports'))
    with pytest.raises(RuntimeError):
        await ej.perform_export_batch('bitcoin')

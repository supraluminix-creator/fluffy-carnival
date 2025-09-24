import os
from pathlib import Path
import pytest

import pipeline.export_job as export_job
import pipeline.export_utils as export_utils
from pipeline.metrics import EXPORTS_TOTAL, EXPORT_ROWS_TOTAL


def _std_record(metric: str, val: float = 1.0):
    return {
        "timestamp": 1,
        "asset": "bitcoin",
        "metric_name": metric,
        "value": val,
        "source": metric,
        "confidence_score": 1.0,
    }


@pytest.mark.asyncio
async def test_export_batch_success_mixed_sync_async(tmp_path, monkeypatch):
    """Succès batch: mélange de collectors sync/async + vérif métriques & fichiers.

    Ce test couvre:
      - _maybe_await (collectors async et sync)
      - création latest_export.csv + pipeline_export_<timestamp>.csv
      - incrément métriques EXPORTS_TOTAL et EXPORT_ROWS_TOTAL
      - passage run_id (facultatif) sans échec si défini
    """
    export_dir = tmp_path / "exports"
    monkeypatch.setenv("EXPORT_DIR", str(export_dir))
    monkeypatch.setenv("RUN_ID", "TESTRUN")

    # Collectors patchés (certains async, d'autres sync) - mêmes noms que dans export_job.tasks
    async def macro(symbol: str, cmc_api_key=None):
        return _std_record("macro", 10)

    def txcount(*a, **k):
        return _std_record("txcount", 2)

    async def hashrate(*a, **k):
        return _std_record("hashrate", 3)

    def sopr(*a, **k):
        return _std_record("sopr", 4)

    async def bybit_oi(*a, **k):
        return _std_record("bybit_oi", 5)

    def bybit_lsr(*a, **k):
        return _std_record("bybit_lsr", 6)

    async def defi(*a, **k):
        return _std_record("defillama", 7)

    def sentiment(*a, **k):
        return _std_record("sentiment", 8)

    monkeypatch.setattr(export_job, "fetch_macro", macro)
    monkeypatch.setattr(export_job, "fetch_txcount", txcount)
    monkeypatch.setattr(export_job, "fetch_hashrate", hashrate)
    monkeypatch.setattr(export_job, "fetch_sopr", sopr)
    monkeypatch.setattr(export_job, "fetch_bybit_oi", bybit_oi)
    monkeypatch.setattr(export_job, "fetch_bybit_long_short_ratio", bybit_lsr)
    monkeypatch.setattr(export_job, "fetch_defillama_tvl", defi)
    monkeypatch.setattr(export_job, "fetch_fear_greed", sentiment)

    summary = await export_job.perform_export_batch("bitcoin")

    assert summary["records"] == 8
    latest = Path(summary["latest"])
    ts = Path(summary["timestamped"])
    assert latest.exists(), "latest_export.csv absent"
    assert ts.exists(), "timestamped export absent"
    assert latest.name == "latest_export.csv"
    # Vérifie au moins 8 lignes (en-tête + 8 records) dans latest
    content = latest.read_text().strip().splitlines()
    assert len(content) >= 9
    # Métriques succès
    assert EXPORTS_TOTAL.labels(status="success")._value.get() >= 1
    assert EXPORT_ROWS_TOTAL.labels(status="success")._value.get() >= 8


@pytest.mark.asyncio
async def test_export_batch_no_data_raises(tmp_path, monkeypatch):
    """Tous collectors None -> RuntimeError (évite faux positif readiness)."""
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))

    async def none_async(*a, **k):
        return None

    def none_sync(*a, **k):
        return None

    monkeypatch.setattr(export_job, "fetch_macro", none_async)
    monkeypatch.setattr(export_job, "fetch_txcount", none_sync)
    monkeypatch.setattr(export_job, "fetch_hashrate", none_async)
    monkeypatch.setattr(export_job, "fetch_sopr", none_sync)
    monkeypatch.setattr(export_job, "fetch_bybit_oi", none_async)
    monkeypatch.setattr(export_job, "fetch_bybit_long_short_ratio", none_sync)
    monkeypatch.setattr(export_job, "fetch_defillama_tvl", none_async)
    monkeypatch.setattr(export_job, "fetch_fear_greed", none_sync)

    with pytest.raises(RuntimeError):
        await export_job.perform_export_batch("bitcoin")


def test_export_utils_direct_write(tmp_path, monkeypatch):
    """Test direct d'export_latest_and_timestamped (chemin utilitaire)."""
    monkeypatch.chdir(tmp_path)
    rows = [{"metric_name": "m", "value": 1, "timestamp": 1, "asset": "bitcoin"}]
    latest, ts = export_utils.export_latest_and_timestamped(rows)
    assert Path(latest).exists()
    assert Path(ts).exists()
    # Vérifie présence d'un fichier timestamped unique
    ts_files = list((tmp_path / "exports").glob("pipeline_export_*.csv"))
    assert len(ts_files) == 1
    # Vérifie manifeste append-only
    manifest = tmp_path / "exports" / "export_manifest.jsonl"
    assert manifest.exists(), "Le manifeste export_manifest.jsonl doit être créé"
    lines = manifest.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    import json
    rec = json.loads(lines[0])
    assert rec["row_count"] == 1
    assert rec["sha256"] and len(rec["sha256"]) >= 10
    assert rec["latest_path"].endswith("latest_export.csv")
    assert rec["timestamped_path"].endswith(".csv")

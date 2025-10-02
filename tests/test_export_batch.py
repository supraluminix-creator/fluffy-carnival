import os

import pytest


@pytest.mark.asyncio
async def test_perform_export_batch_success(tmp_path, monkeypatch):
    """Vérifie qu'un export batch crée bien latest + timestamped CSV.

    On monkeypatch chaque collector référencé dans perform_export_batch pour
    retourner un enregistrement dict minimal cohérent. Mélange sync/async pour
    couvrir _maybe_await.
    """
    export_dir = tmp_path / "exports"
    monkeypatch.setenv("EXPORT_DIR", str(export_dir))

    from pipeline import export_job

    # Fabrique de records standardisés
    def make_record(metric: str, source: str = "test"):
        return {
            "timestamp": "2025-09-21T00:00:00Z",
            "asset": "bitcoin",
            "symbol": "BTCUSD",  # ajouté pour validation
            "chain": "-",        # valeur par défaut attendue
            "metric_name": metric,
            "value": 123.45,
            "source": source,
            "confidence_score": 1.0,
        }

    # Patch collectors (certains async, d'autres sync)
    async def async_collector(*args, **kwargs):
        return make_record("async_metric")

    def sync_collector(*args, **kwargs):  # pragma: no cover - exécuté
        return make_record("sync_metric")

    monkeypatch.setattr(export_job, "fetch_macro", async_collector)
    monkeypatch.setattr(export_job, "fetch_txcount", sync_collector)
    monkeypatch.setattr(export_job, "fetch_hashrate", async_collector)
    monkeypatch.setattr(export_job, "fetch_sopr", sync_collector)
    monkeypatch.setattr(export_job, "fetch_bybit_oi", async_collector)
    monkeypatch.setattr(export_job, "fetch_bybit_long_short_ratio", sync_collector)
    monkeypatch.setattr(export_job, "fetch_defillama_tvl", async_collector)
    monkeypatch.setattr(export_job, "fetch_fear_greed", sync_collector)

    result = await export_job.perform_export_batch(symbol="bitcoin")

    # Assertions sur le résumé
    assert result["records"] > 0
    assert os.path.isfile(result["latest"]), "latest_export.csv manquant"
    assert os.path.isfile(result["timestamped"]), "timestamped export manquant"
    # Vérifie que latest_export.csv est bien dans le répertoire d'export
    assert result["latest"].endswith("latest_export.csv")


@pytest.mark.asyncio
async def test_perform_export_batch_no_data(tmp_path, monkeypatch):
    """Tous les collectors échouent / None => RuntimeError attendue."""
    export_dir = tmp_path / "exports"
    monkeypatch.setenv("EXPORT_DIR", str(export_dir))

    from pipeline import export_job

    async def failing(*args, **kwargs):  # pragma: no cover - executed
        raise RuntimeError("boom")

    # Patch toutes les fonctions en échec
    monkeypatch.setattr(export_job, "fetch_macro", failing)
    monkeypatch.setattr(export_job, "fetch_txcount", failing)
    monkeypatch.setattr(export_job, "fetch_hashrate", failing)
    monkeypatch.setattr(export_job, "fetch_sopr", failing)
    monkeypatch.setattr(export_job, "fetch_bybit_oi", failing)
    monkeypatch.setattr(export_job, "fetch_bybit_long_short_ratio", failing)
    monkeypatch.setattr(export_job, "fetch_defillama_tvl", failing)
    monkeypatch.setattr(export_job, "fetch_fear_greed", failing)

    with pytest.raises(RuntimeError):
        await export_job.perform_export_batch(symbol="bitcoin")

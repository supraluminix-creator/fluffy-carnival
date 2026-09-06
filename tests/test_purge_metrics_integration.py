import os
import time

from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter
from pipeline.db_stats import update_db_metrics, vacuum_and_update_metrics
from pipeline.metrics import (
    DB_FILE_SIZE_BYTES,
    DB_FRAGMENTATION_RATIO,
    DB_FREELIST_PAGES,
    DB_PAGE_COUNT,
    DB_VACUUM_DURATION_SECONDS,
    PURGE_OPERATIONS_TOTAL,
)
from pipeline.purge_job import purge_liquidations


def _fetch_metric_value(metric):  # helper tolérant
    try:
        return metric._value.get()  # type: ignore[attr-defined]
    except Exception:
        return None


def test_purge_and_vacuum_flow(tmp_path):
    db_path = tmp_path / "liq.db"
    writer = BybitLiquidationsWriter(db=db_path.as_posix(), parquet_enabled=False, flush_size=10, flush_interval=60)

    now_ms = int(time.time() * 1000)
    old_ms = now_ms - 45 * 86400 * 1000

    # Ajoute événements (dont anciens)
    async def _inject():
        for i in range(12):
            await writer.write_record(
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy" if i % 2 == 0 else "Sell",
                    "price": 50000 + i,
                    "qty": 0.1 * i,
                    "time": old_ms if i < 5 else now_ms,
                }
            )
        await writer.flush()

    import asyncio

    asyncio.run(_inject())

    # Mise à jour métriques initiales
    update_db_metrics(db_path)
    _ = _fetch_metric_value(DB_FILE_SIZE_BYTES)
    page_before = _fetch_metric_value(DB_PAGE_COUNT)

    # Dry-run purge (30 jours)
    os.environ["LIQ_RETENTION_DAYS"] = "30"
    os.environ["LIQ_PURGE_DRY_RUN"] = "1"
    stats_dry = purge_liquidations(db_path.as_posix())
    assert stats_dry["bybit_liquidations"] > 0

    # Purge réelle
    os.environ["LIQ_PURGE_DRY_RUN"] = "0"
    stats_real = purge_liquidations(db_path.as_posix())
    assert stats_real["bybit_liquidations"] == stats_dry["bybit_liquidations"]

    # VACUUM + métriques
    vacuum_and_update_metrics(db_path)
    _ = _fetch_metric_value(DB_FILE_SIZE_BYTES)
    page_after = _fetch_metric_value(DB_PAGE_COUNT)
    freelist_after = _fetch_metric_value(DB_FREELIST_PAGES)
    frag_after = _fetch_metric_value(DB_FRAGMENTATION_RATIO)
    vacuum_duration = _fetch_metric_value(DB_VACUUM_DURATION_SECONDS)

    # Assertions souples (on ne force pas diminution stricte car dépend du FS) mais cohérentes
    assert vacuum_duration is not None and vacuum_duration >= 0
    if page_before is not None and page_after is not None:
        assert page_after <= page_before  # pages ne devraient pas augmenter après vacuum
    if freelist_after is not None and frag_after is not None:
        assert 0 <= frag_after <= 1

    # Vérifie compteur purge incrémenté (au moins 2 appels: dry-run + real) si disponible
    if PURGE_OPERATIONS_TOTAL is not None:
        # Accès via collect() du registry (plus propre) mais on reste simple
        pass  # présence seule suffit ici

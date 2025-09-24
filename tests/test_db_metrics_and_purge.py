import os
import sqlite3
import time
from pathlib import Path

import pytest

from pipeline.db_stats import update_db_metrics
from pipeline.purge_job import purge_liquidations
from pipeline.metrics import DB_FILE_SIZE_BYTES, DB_LIQUIDATIONS_ROWS


def _create_db(path: Path):
    conn = sqlite3.connect(path.as_posix())
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bybit_liquidations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            side TEXT,
            price REAL,
            qty REAL,
            time INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bybit_liquidations_hourly (
            hour_start INTEGER PRIMARY KEY,
            symbol TEXT,
            total_qty REAL,
            buy_qty REAL,
            sell_qty REAL
        )
        """
    )
    conn.commit()
    conn.close()


def test_db_metrics_and_purge(tmp_path):
    db_path = tmp_path / "crypto.db"
    _create_db(db_path)

    # insère lignes: 1 ancienne, 1 récente
    now = int(time.time())
    old_ts_ms = (now - 60 * 60 * 24 * 40) * 1000  # 40 jours
    new_ts_ms = now * 1000

    conn = sqlite3.connect(db_path.as_posix())
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bybit_liquidations(symbol, side, price, qty, time) VALUES (?,?,?,?,?)",
        ("BTCUSDT", "Buy", 50000, 1.2, old_ts_ms),
    )
    cur.execute(
        "INSERT INTO bybit_liquidations(symbol, side, price, qty, time) VALUES (?,?,?,?,?)",
        ("BTCUSDT", "Sell", 51000, 0.8, new_ts_ms),
    )
    # hourly
    cur.execute(
        "INSERT INTO bybit_liquidations_hourly(hour_start, symbol, total_qty, buy_qty, sell_qty) VALUES (?,?,?,?,?)",
        (now - 60 * 60 * 24 * 40, "BTCUSDT", 10, 6, 4),
    )
    cur.execute(
        "INSERT INTO bybit_liquidations_hourly(hour_start, symbol, total_qty, buy_qty, sell_qty) VALUES (?,?,?,?,?)",
        (now, "BTCUSDT", 5, 3, 2),
    )
    conn.commit()
    conn.close()

    update_db_metrics(db_path)
    # Vérifications soft: juste que gauges appelables sans exception
    if DB_FILE_SIZE_BYTES is not None:
        assert DB_FILE_SIZE_BYTES._value.get() > 0  # type: ignore[attr-defined]
    if DB_LIQUIDATIONS_ROWS is not None:
        # 2 lignes hourly avant purge
        assert DB_LIQUIDATIONS_ROWS._value.get() == 2  # type: ignore[attr-defined]

    # Dry-run purge (doit compter mais ne pas supprimer)
    os.environ["LIQ_RETENTION_DAYS"] = "30"
    os.environ["LIQ_PURGE_DRY_RUN"] = "1"
    stats = purge_liquidations(db_path.as_posix())
    assert stats["bybit_liquidations"] == 1
    assert stats["bybit_liquidations_hourly"] == 1

    # Purge réelle
    os.environ["LIQ_PURGE_DRY_RUN"] = "0"
    stats_real = purge_liquidations(db_path.as_posix())
    assert stats_real["bybit_liquidations"] == 1
    assert stats_real["bybit_liquidations_hourly"] == 1

    # Vérifie qu'il reste les lignes récentes
    conn = sqlite3.connect(db_path.as_posix())
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) FROM bybit_liquidations")
    remaining_events = cur.fetchone()[0]
    cur.execute("SELECT COUNT(1) FROM bybit_liquidations_hourly")
    remaining_hourly = cur.fetchone()[0]
    conn.close()
    assert remaining_events == 1
    assert remaining_hourly == 1

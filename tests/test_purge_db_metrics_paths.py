import sqlite3
import time

import pytest

from pipeline.db_stats import update_db_metrics, vacuum_and_update_metrics
from pipeline.metrics import (
    DB_FILE_SIZE_BYTES,
    DB_VACUUM_DURATION_SECONDS,
    PURGE_OPERATIONS_TOTAL,
)
from pipeline.purge_job import DRY_ENV, PURGE_ENV, purge_liquidations

SCHEMA = [
    "CREATE TABLE bybit_liquidations(time INTEGER, symbol TEXT, amount REAL)",
    "CREATE TABLE bybit_liquidations_hourly(hour_start INTEGER, symbol TEXT, amount REAL)"
]

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / 'crypto.db'
    conn = sqlite3.connect(db_file.as_posix())
    try:
        for ddl in SCHEMA:
            conn.execute(ddl)
        # Insert rows: some old, some recent
        now = int(time.time())
        rows_liq = [ ( (now-40*86400)*1000, 'BTCUSDT', 1.0), ( (now-10*86400)*1000, 'ETHUSDT', 2.0) ]
        rows_hourly = [ (now-40*86400, 'BTCUSDT', 1.0), (now-5*86400, 'ETHUSDT', 2.0) ]
        conn.executemany("INSERT INTO bybit_liquidations VALUES (?,?,?)", rows_liq)
        conn.executemany("INSERT INTO bybit_liquidations_hourly VALUES (?,?,?)", rows_hourly)
        conn.commit()
    finally:
        conn.close()
    return db_file


def _metric_value(counter, **labels):
    try:
        return counter.labels(**labels)._value.get()
    except Exception:
        return None


def test_purge_dry_run(monkeypatch, temp_db):
    monkeypatch.setenv(PURGE_ENV, '30')  # retention 30j => supprime lignes plus anciennes
    monkeypatch.setenv(DRY_ENV, '1')
    stats = purge_liquidations(temp_db.as_posix())
    assert stats.get('bybit_liquidations') >= 1
    assert stats.get('bybit_liquidations_hourly') >= 1
    # Metrics inc dry_run
    v = _metric_value(PURGE_OPERATIONS_TOTAL, table='bybit_liquidations', status='ok', mode='dry_run')
    assert v is not None and v >= 1


def test_purge_real_then_vacuum(monkeypatch, temp_db):
    monkeypatch.setenv(PURGE_ENV, '30')
    monkeypatch.delenv(DRY_ENV, raising=False)
    stats = purge_liquidations(temp_db.as_posix())
    # Should delete at least 1 per table
    assert stats['bybit_liquidations'] >= 1
    assert stats['bybit_liquidations_hourly'] >= 1
    # After real purge, run vacuum + metrics update
    update_db_metrics(temp_db.as_posix())
    size_before = DB_FILE_SIZE_BYTES._value.get() if DB_FILE_SIZE_BYTES else None
    vacuum_and_update_metrics(temp_db.as_posix())
    if DB_VACUUM_DURATION_SECONDS:
        assert DB_VACUUM_DURATION_SECONDS._value.get() >= 0.0
    size_after = DB_FILE_SIZE_BYTES._value.get() if DB_FILE_SIZE_BYTES else None
    # Size after vacuum can be <= before (shrink) but both should be numeric
    assert size_before is not None and size_after is not None

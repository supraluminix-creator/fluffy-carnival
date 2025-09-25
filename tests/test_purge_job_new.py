import sqlite3
from pathlib import Path

from pipeline.purge_job import purge_liquidations


def _make_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path.as_posix())
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS bybit_liquidations (time INTEGER, v TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS bybit_liquidations_hourly (hour_start INTEGER, v TEXT)")
    # Insert quelques lignes anciennes (timestamp très bas)
    cur.execute("INSERT INTO bybit_liquidations VALUES (?, ?)", (1, 'a'))
    cur.execute("INSERT INTO bybit_liquidations_hourly VALUES (?, ?)", (1, 'b'))
    conn.commit()
    conn.close()


def test_purge_liquidations_dry_and_real(tmp_path, monkeypatch):
    dbp = tmp_path / 'crypto.db'
    _make_db(dbp)
    monkeypatch.setenv('LIQ_RETENTION_DAYS', '0')  # cutoff maintenant
    monkeypatch.setenv('LIQ_PURGE_DRY_RUN', '1')
    dry = purge_liquidations(dbp.as_posix())
    assert dry['bybit_liquidations'] >= 1 and dry['bybit_liquidations_hourly'] >= 1
    # Real purge
    monkeypatch.delenv('LIQ_PURGE_DRY_RUN')
    real = purge_liquidations(dbp.as_posix())
    assert real['bybit_liquidations'] >= 1 and real['bybit_liquidations_hourly'] >= 1

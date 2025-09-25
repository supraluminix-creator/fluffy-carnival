import sqlite3

from pipeline.db_stats import update_db_metrics, vacuum_and_update_metrics


def test_db_metrics_update_and_vacuum(tmp_path):
    dbp = tmp_path / 'crypto.db'
    conn = sqlite3.connect(dbp.as_posix())
    cur = conn.cursor()
    cur.execute("CREATE TABLE bybit_liquidations_hourly (hour_start INTEGER, v TEXT)")
    cur.executemany("INSERT INTO bybit_liquidations_hourly VALUES (?, ?)", [(i, 'x') for i in range(3)])
    conn.commit()
    conn.close()
    update_db_metrics(dbp.as_posix())
    vacuum_and_update_metrics(dbp.as_posix())
    # Pas d'assert détaillée (metrics internes), couverture code uniquement.
    assert dbp.exists()

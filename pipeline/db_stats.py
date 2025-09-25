"""Remplacement de l'ancien module db_metrics.

Expose les fonctions de mise à jour des métriques SQLite:
 - update_db_metrics
 - vacuum_and_update_metrics

Le module legacy `db_metrics.py` a été supprimé; importer désormais:
    from pipeline.db_stats import update_db_metrics
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .metrics import (
    DB_FILE_SIZE_BYTES,
    DB_FRAGMENTATION_RATIO,
    DB_FREELIST_PAGES,
    DB_LIQUIDATIONS_ROWS,
    DB_PAGE_COUNT,
    DB_VACUUM_DURATION_SECONDS,
)

DEFAULT_DB_PATH = Path("data/crypto.db")


def get_db_path() -> Path:
    return DEFAULT_DB_PATH


def update_db_metrics(db_path: str | Path | None = None) -> None:
    p = Path(db_path) if db_path else get_db_path()
    try:
        if DB_FILE_SIZE_BYTES is not None and p.exists():  # type: ignore[truthy-function]
            DB_FILE_SIZE_BYTES.set(p.stat().st_size)  # type: ignore[union-attr]
    except Exception:
        pass

    try:
        if p.exists():
            conn = sqlite3.connect(p.as_posix())
            try:
                if DB_LIQUIDATIONS_ROWS is not None:
                    try:
                        cur = conn.execute("SELECT COUNT(1) FROM bybit_liquidations_hourly")
                        count = cur.fetchone()[0]
                        DB_LIQUIDATIONS_ROWS.set(count)  # type: ignore[union-attr]
                    except sqlite3.OperationalError:
                        pass
                if DB_PAGE_COUNT is not None or DB_FREELIST_PAGES is not None:
                    try:
                        cur = conn.execute("PRAGMA page_count")
                        page_count = cur.fetchone()[0]
                        cur = conn.execute("PRAGMA freelist_count")
                        freelist = cur.fetchone()[0]
                        if DB_PAGE_COUNT is not None:
                            DB_PAGE_COUNT.set(page_count)  # type: ignore[union-attr]
                        if DB_FREELIST_PAGES is not None:
                            DB_FREELIST_PAGES.set(freelist)  # type: ignore[union-attr]
                        if DB_FRAGMENTATION_RATIO is not None and page_count:
                            DB_FRAGMENTATION_RATIO.set(freelist / page_count)  # type: ignore[union-attr]
                    except Exception:
                        pass
            finally:
                conn.close()
    except Exception:
        pass


def vacuum_and_update_metrics(db_path: str | Path | None = None) -> None:
    p = Path(db_path) if db_path else get_db_path()
    if not p.exists():
        return
    start = time.time()
    try:
        conn = sqlite3.connect(p.as_posix())
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
    finally:
        duration = time.time() - start
        try:
            if DB_VACUUM_DURATION_SECONDS is not None:
                DB_VACUUM_DURATION_SECONDS.set(duration)  # type: ignore[union-attr]
        except Exception:
            pass
    update_db_metrics(p)

__all__ = ["update_db_metrics", "vacuum_and_update_metrics", "get_db_path"]

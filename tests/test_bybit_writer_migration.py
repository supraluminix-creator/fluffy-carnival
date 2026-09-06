from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter


def _create_legacy_schema(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Legacy raw table without qty_usd column
    cur.execute(
        """
        CREATE TABLE bybit_liquidations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            qty REAL NOT NULL,
            time INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Legacy hourly table (structure compatible but totals missing)
    cur.execute(
        """
        CREATE TABLE bybit_liquidations_hourly (
            hour_start INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            total_qty_usd REAL NOT NULL DEFAULT 0,
            events_count INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(hour_start, symbol, side)
        )
        """
    )
    # Seed one liquidation without USD notional
    cur.execute(
        """
        INSERT INTO bybit_liquidations(symbol, side, price, qty, time)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("BTCUSDT", "BUY", 112_000.0, 0.5, 1_760_486_400_000),
    )
    conn.commit()
    conn.close()


def test_writer_migrates_legacy_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _create_legacy_schema(db_path)

    writer = BybitLiquidationsWriter(db=str(db_path))
    writer.close()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(bybit_liquidations)")
    columns = {row[1] for row in cur.fetchall()}
    assert "qty_usd" in columns

    cur.execute(
        "SELECT qty_usd FROM bybit_liquidations WHERE symbol=?",
        ("BTCUSDT",),
    )
    qty_usd = cur.fetchone()[0]
    assert qty_usd == pytest.approx(112_000.0 * 0.5)

    cur.execute(
        """
        SELECT total_qty_usd, events_count
          FROM bybit_liquidations_hourly
         WHERE symbol=? AND side=?
        """,
        ("BTCUSDT", "BUY"),
    )
    row = cur.fetchone()
    assert row is not None
    total_qty_usd, events_count = row
    assert total_qty_usd == pytest.approx(112_000.0 * 0.5)
    assert events_count == 1

    conn.close()

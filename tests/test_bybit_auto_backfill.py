from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter
from tools.bybit_liq_auto_backfill import Range, _compute_missing_ranges, _group_missing_days


def _insert_event(db_path: Path, symbol: str, event_date: date) -> None:
    writer = BybitLiquidationsWriter(db=str(db_path))
    ts = datetime(event_date.year, event_date.month, event_date.day, 12, tzinfo=UTC)
    writer.write_many(
        [
            {
                "symbol": symbol,
                "side": "BUY",
                "price": 50_000.0,
                "qty": 0.5,
                "time": int(ts.timestamp() * 1000),
            }
        ]
    )
    writer.flush_sync()
    writer.close()


def test_group_missing_days_merges_contiguous() -> None:
    days = [date(2025, 10, 9), date(2025, 10, 10), date(2025, 10, 11), date(2025, 10, 13)]
    ranges = _group_missing_days(days)
    assert ranges == [Range(date(2025, 10, 9), date(2025, 10, 11)), Range(date(2025, 10, 13), date(2025, 10, 13))]


def test_compute_missing_ranges_detects_gaps(tmp_path: Path) -> None:
    db_path = tmp_path / "crypto.db"
    _insert_event(db_path, "BTCUSDT", date(2025, 10, 10))

    conn = sqlite3.connect(db_path)
    missing_days, ranges = _compute_missing_ranges(
        conn,
        "BTCUSDT",
        date(2025, 10, 9),
        date(2025, 10, 11),
    )
    conn.close()

    assert missing_days == [date(2025, 10, 9), date(2025, 10, 11)]
    assert ranges == [Range(date(2025, 10, 9), date(2025, 10, 9)), Range(date(2025, 10, 11), date(2025, 10, 11))]

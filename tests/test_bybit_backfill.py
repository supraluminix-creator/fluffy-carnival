from __future__ import annotations

import csv
import gzip
import sqlite3
from datetime import date
from pathlib import Path
from typing import cast

import pytest

from pipeline.collectors.bybit_backfill import BackfillOptions, backfill

HEADERS = ["timestamp", "symbol", "side", "price", "qty"]


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_csv_gz(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_backfill_ingests_csv_into_sqlite(tmp_path: Path) -> None:
    rows = [
        {
            "timestamp": 1739059200000,
            "symbol": "BTCUSDT",
            "side": "Buy",
            "price": 50000,
            "qty": 0.5,
        },
        {
            "timestamp": 1739059260000,
            "symbol": "BTCUSDT",
            "side": "Sell",
            "price": 50500,
            "qty": 0.3,
        },
        {  # Duplicate row should be ignored by ingest_file
            "timestamp": 1739059260000,
            "symbol": "BTCUSDT",
            "side": "Sell",
            "price": 50500,
            "qty": 0.3,
        },
    ]
    csv_path = tmp_path / "BTCUSDT" / "BTCUSDT2025-02-09.csv.gz"
    _write_csv_gz(csv_path, rows)

    db_path = tmp_path / "crypto.db"
    options = BackfillOptions(
        symbols=["BTCUSDT"],
        start=date(2025, 2, 9),
        end=date(2025, 2, 9),
        cache_dir=tmp_path,
        db_path=db_path,
        parquet_dir=None,
        flush_size=2,
        dry_run=False,
    )

    summary = backfill(options)
    assert summary["dry_run"] is False
    symbols_stats = cast(dict[str, dict[str, int]], summary["symbols"])
    stats = symbols_stats["BTCUSDT"]
    assert stats["files"] == 1
    assert stats["rows"] == 2  # Duplicate removed

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM bybit_liquidations")
    assert cur.fetchone()[0] == 2

    cur.execute(
        "SELECT COUNT(*), SUM(events_count) FROM bybit_liquidations_hourly WHERE symbol=?",
        ("BTCUSDT",),
    )
    hourly_rows, events_count = cur.fetchone()
    assert hourly_rows >= 1
    assert events_count == 2
    conn.close()


def test_backfill_dry_run_counts_rows_without_writing(tmp_path: Path) -> None:
    rows = [
        {
            "timestamp": 1739145600000,
            "symbol": "ETHUSDT",
            "side": "Sell",
            "price": 3200.5,
            "qty": 12.0,
        },
        {
            "timestamp": 1739145660000,
            "symbol": "ETHUSDT",
            "side": "Buy",
            "price": 3199.1,
            "qty": 3.2,
        },
    ]
    gz_path = tmp_path / "ETHUSDT" / "ETHUSDT2025-02-10.csv.gz"
    _write_csv_gz(gz_path, rows)

    options = BackfillOptions(
        symbols=["ETHUSDT"],
        start=date(2025, 2, 10),
        end=date(2025, 2, 10),
        cache_dir=tmp_path,
        db_path=tmp_path / "unused.db",
        parquet_dir=None,
        flush_size=10,
        dry_run=True,
    )

    summary = backfill(options)
    assert summary["dry_run"] is True
    symbols_stats = cast(dict[str, dict[str, int]], summary["symbols"])
    stats = symbols_stats["ETHUSDT"]
    assert stats["files"] == 1
    assert stats["rows"] == 2

    # Ensure DB file not created in dry-run mode
    assert not (tmp_path / "unused.db").exists()


@pytest.mark.parametrize(
    "missing_field",
    ["symbol", "timestamp", "price", "qty"],
)
def test_iterators_skip_incomplete_rows(tmp_path: Path, missing_field: str) -> None:
    row = {
        "timestamp": 1739145600000,
        "symbol": "RNDRUSDT",
        "side": "Sell",
        "price": 9.12,
        "qty": 4.5,
    }
    row.pop(missing_field)
    csv_path = tmp_path / "RNDRUSDT" / "RNDRUSDT2025-02-10.csv"
    _write_csv(csv_path, [row])

    options = BackfillOptions(
        symbols=["RNDRUSDT"],
        start=date(2025, 2, 10),
        end=date(2025, 2, 10),
        cache_dir=tmp_path,
        db_path=tmp_path / "rn.db",
        parquet_dir=None,
        flush_size=5,
        dry_run=False,
    )

    summary = backfill(options)
    symbols_stats = cast(dict[str, dict[str, int]], summary["symbols"])
    stats = symbols_stats["RNDRUSDT"]
    assert stats["rows"] == 0

    conn = sqlite3.connect(options.db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='bybit_liquidations'")
    exists = cur.fetchone()[0]
    if exists:
        cur.execute("SELECT COUNT(*) FROM bybit_liquidations")
        assert cur.fetchone()[0] == 0
    conn.close()

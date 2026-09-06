from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import structlog

from pipeline.collectors.bybit_backfill import BackfillOptions, backfill
from pipeline.logging_config import setup_logging
from pipeline.storage.sqlite_adapter import get_default_db_path

setup_logging(simple=True)
logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Range:
    start: date
    end: date

    def to_json(self) -> tuple[str, str]:
        return (self.start.isoformat(), self.end.isoformat())


def _daterange(start: date, end: date) -> Iterable[date]:
    current = start
    delta = timedelta(days=1)
    while current <= end:
        yield current
        current += delta


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _fetch_present_days(conn: sqlite3.Connection, symbol: str, start: date, end: date) -> set[date]:
    try:
        conn.execute("SELECT 1 FROM bybit_liquidations LIMIT 1")
    except sqlite3.OperationalError:
        return set()

    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)

    cur = conn.execute(
        "SELECT DISTINCT time FROM bybit_liquidations WHERE symbol=? AND time BETWEEN ? AND ?",
        (symbol, start_ts, end_ts),
    )
    present: set[date] = set()
    for (time_ms,) in cur.fetchall():
        dt = datetime.fromtimestamp(int(time_ms) / 1000, tz=UTC)
        present.add(dt.date())
    return present


def _group_missing_days(days: list[date]) -> list[Range]:
    if not days:
        return []
    ranges: list[Range] = []
    start = prev = days[0]
    for day in days[1:]:
        if (day - prev).days == 1:
            prev = day
            continue
        ranges.append(Range(start, prev))
        start = prev = day
    ranges.append(Range(start, prev))
    return ranges


def _compute_missing_ranges(
    conn: sqlite3.Connection,
    symbol: str,
    start: date,
    end: date,
) -> tuple[list[date], list[Range]]:
    target_days = list(_daterange(start, end))
    present = _fetch_present_days(conn, symbol, start, end)
    missing = [day for day in target_days if day not in present]
    ranges = _group_missing_days(missing)
    return missing, ranges


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto backfill missing Bybit liquidation days")
    parser.add_argument(
        "--symbols",
        required=True,
        help="Comma-separated symbols (e.g. BTCUSDT,ETHUSDT)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of trailing days to inspect (default: 30)",
    )
    parser.add_argument(
        "--start",
        help="Optional explicit start date (YYYY-MM-DD). Overrides --days",
    )
    parser.add_argument(
        "--end",
        help="Optional explicit end date (YYYY-MM-DD). Defaults to today UTC",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(get_default_db_path()),
        help="SQLite DB path",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/bybit_public"),
        help="Directory for cached CSV files",
    )
    parser.add_argument(
        "--parquet-dir",
        type=Path,
        default=Path("data/bybit_liquidations"),
        help="Optional Parquet output directory (empty string to disable)",
    )
    parser.add_argument(
        "--base-url",
        default="https://public.bybit.com/trading",
        help="Base URL for Bybit public CSV archives",
    )
    parser.add_argument(
        "--flush-size",
        type=int,
        default=500,
        help="Writer flush size for backfill batches",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report missing ranges, do not download or write",
    )
    return parser.parse_args()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> int:
    args = _parse_args()

    today = datetime.now(tz=UTC).date()
    end_date = _parse_date(args.end) or today
    if end_date > today:
        end_date = today

    start_date = _parse_date(args.start)
    if start_date is None:
        days = max(args.days, 1)
        start_date = end_date - timedelta(days=days - 1)

    if start_date > end_date:
        raise SystemExit("--start must be before --end")

    symbols = [_normalize_symbol(sym) for sym in args.symbols.split(",") if sym.strip()]
    if not symbols:
        raise SystemExit("No symbols provided")

    db_path = args.db
    parquet_dir: Path | None = args.parquet_dir if str(args.parquet_dir).strip() else None

    if not db_path.exists():
        logger.info("auto_backfill_db_missing", db=str(db_path))
        conn = sqlite3.connect(":memory:")
    else:
        logger.info("auto_backfill_db_found", db=str(db_path))
        conn = sqlite3.connect(db_path)

    try:
        results: dict[str, Any] = {}
        for symbol in symbols:
            missing_days, ranges = _compute_missing_ranges(conn, symbol, start_date, end_date)
            logger.info(
                "auto_backfill_missing",
                symbol=symbol,
                missing=len(missing_days),
                ranges=len(ranges),
            )

            runs: list[dict[str, Any]] = []
            if not args.dry_run and ranges:
                for range_ in ranges:
                    options = BackfillOptions(
                        symbols=[symbol],
                        start=range_.start,
                        end=range_.end,
                        base_url=args.base_url,
                        cache_dir=args.cache_dir,
                        db_path=db_path,
                        parquet_dir=parquet_dir,
                        flush_size=args.flush_size,
                        dry_run=False,
                    )
                    summary = backfill(options)
                    symbols_summary = cast(dict[str, Any], summary.get("symbols", {}))
                    stats = cast(dict[str, Any], symbols_summary.get(symbol, {"files": 0, "rows": 0}))
                    runs.append(
                        {
                            "start": range_.start.isoformat(),
                            "end": range_.end.isoformat(),
                            "files": int(stats.get("files", 0)),
                            "rows": int(stats.get("rows", 0)),
                        }
                    )

            results[symbol] = {
                "missing_days": [day.isoformat() for day in missing_days],
                "ranges": [range_.to_json() for range_ in ranges],
                "runs": runs,
            }
    finally:
        conn.close()

    output = {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "dry_run": bool(args.dry_run),
        "symbols": results,
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

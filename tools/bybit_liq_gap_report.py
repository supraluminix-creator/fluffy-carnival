from __future__ import annotations

import argparse
import json
import sqlite3
import zipfile
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import structlog

from pipeline.logging_config import setup_logging
from pipeline.storage.sqlite_adapter import get_default_db_path

setup_logging(simple=True)
logger = structlog.get_logger(__name__)


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:  # pragma: no cover - guard user input
        raise argparse.ArgumentTypeError(f"Invalid date '{value}': expected YYYY-MM-DD") from exc


def _extract_day_from_name(name: str) -> date | None:
    cleaned = name
    for suffix in (".csv.gz", ".csv", ".gz"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    day_str = cleaned[-10:]
    try:
        return datetime.strptime(day_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def _collect_cache_days(symbol: str, cache_dir: Path) -> set[date]:
    days: set[date] = set()
    symbol_dir = cache_dir / symbol
    if not symbol_dir.exists():
        return days
    for path in symbol_dir.iterdir():
        if not path.is_file():
            continue
        day = _extract_day_from_name(path.name)
        if day is not None:
            days.add(day)
    return days


def _collect_zip_days(symbol: str, archive_path: Path) -> set[date]:
    days: set[date] = set()
    if not archive_path.exists():
        return days
    with zipfile.ZipFile(archive_path, "r") as zf:
        for name in zf.namelist():
            if not name.lower().startswith(symbol.lower()):
                continue
            day = _extract_day_from_name(Path(name).name)
            if day is not None:
                days.add(day)
    return days


def _fetch_db_range(conn: sqlite3.Connection, symbol: str) -> dict[str, object] | None:
    cur = conn.execute(
        "SELECT MIN(time), MAX(time), COUNT(*) FROM bybit_liquidations WHERE symbol=?",
        (symbol,),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    first_ts, last_ts, count = row
    first_ts = int(first_ts)
    last_ts = int(last_ts)
    first_day = datetime.fromtimestamp(first_ts / 1000, tz=UTC).date()
    last_day = datetime.fromtimestamp(last_ts / 1000, tz=UTC).date()
    return {
        "first_ts": first_ts,
        "last_ts": last_ts,
        "event_count": int(count),
        "first_day": first_day.isoformat(),
        "last_day": last_day.isoformat(),
    }


def _list_symbols_from_db(conn: sqlite3.Connection) -> list[str]:
    try:
        cur = conn.execute("SELECT DISTINCT symbol FROM bybit_liquidations ORDER BY symbol")
        return [row[0] for row in cur.fetchall() if row and row[0]]
    except sqlite3.Error:
        return []


def _iter_symbols(symbols_arg: str | None, conn: sqlite3.Connection, cache_dir: Path) -> Iterable[str]:
    if symbols_arg:
        return [sym.strip().upper() for sym in symbols_arg.split(",") if sym.strip()]
    symbols = set(_list_symbols_from_db(conn))
    for path in cache_dir.iterdir() if cache_dir.exists() else []:
        if path.is_dir():
            symbols.add(path.name.upper())
    return sorted(symbols)


def _compute_missing_days(start: date, end: date, available: set[date]) -> list[str]:
    total_days = (end - start).days + 1
    if total_days <= 0:
        return []
    missing: list[str] = []
    cur = start
    for _ in range(total_days):
        if cur not in available:
            missing.append(cur.isoformat())
        cur += timedelta(days=1)
    return missing


def gap_report(
    *,
    conn: sqlite3.Connection,
    symbols: Iterable[str],
    cache_dir: Path,
    archive_zip: Path | None,
    start: date,
    end: date,
) -> dict[str, object]:
    archive_zip = archive_zip if archive_zip and archive_zip.exists() else None
    results: dict[str, object] = {}
    for symbol in symbols:
        cache_days = _collect_cache_days(symbol, cache_dir)
        zip_days = _collect_zip_days(symbol, archive_zip) if archive_zip else set()
        available_days = cache_days | zip_days
        missing_days = _compute_missing_days(start, end, available_days)
        db_info = _fetch_db_range(conn, symbol)
        results[symbol] = {
            "db": db_info,
            "available_days": sorted(day.isoformat() for day in available_days if start <= day <= end),
            "missing_days": missing_days,
            "sources": {
                "cache_files": len(cache_days),
                "archive_zip": len(zip_days),
            },
        }
    return results


def _open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Bybit liquidation archive coverage and DB gaps")
    parser.add_argument("--symbols", help="Comma-separated symbols (defaults to DB + cache contents)")
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
        help="Directory containing cached Bybit CSV archives",
    )
    parser.add_argument("--archive-zip", type=Path, help="Optional ZIP archive with additional CSV dumps")
    parser.add_argument("--start", type=_parse_date, help="Start date (inclusive) for the gap analysis")
    parser.add_argument("--end", type=_parse_date, help="End date (inclusive) for the gap analysis")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to inspect when --start is omitted (default: 30)",
    )

    args = parser.parse_args()

    if args.end and args.start and args.end < args.start:
        parser.error("--end must be greater or equal to --start")

    today = datetime.now(tz=UTC).date()
    end = args.end or today
    if end > today:
        end = today
    start = args.start if args.start else end - timedelta(days=max(args.days - 1, 0))

    cache_dir = args.cache_dir
    archive_zip = args.archive_zip

    cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        conn = _open_db(args.db)
    except FileNotFoundError as exc:
        parser.error(str(exc))
    try:
        symbols = list(_iter_symbols(args.symbols, conn, cache_dir))
        if not symbols:
            parser.error("No symbols available to inspect (use --symbols)")
        report = gap_report(
            conn=conn,
            symbols=symbols,
            cache_dir=cache_dir,
            archive_zip=archive_zip,
            start=start,
            end=end,
        )
    finally:
        conn.close()

    output = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "db": str(args.db),
        "cache_dir": str(cache_dir),
        "archive_zip": str(archive_zip) if archive_zip else None,
        "symbols": report,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    logger.info("bybit_gap_report_done", symbols=len(report))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())

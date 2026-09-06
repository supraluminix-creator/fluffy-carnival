from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import structlog

from pipeline.collectors.bybit_backfill import BackfillOptions, backfill
from pipeline.logging_config import setup_logging
from pipeline.storage.sqlite_adapter import get_default_db_path

setup_logging(simple=True)
logger = structlog.get_logger(__name__)


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:  # pragma: no cover - user input guard
        raise argparse.ArgumentTypeError(f"Invalid date '{value}': expected YYYY-MM-DD") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Bybit liquidation CSV archives into the local DB")
    parser.add_argument("--symbols", required=True, help="Comma-separated list of symbols, e.g. BTCUSDT,ETHUSDT")
    parser.add_argument(
        "--start",
        required=True,
        type=_parse_date,
        help="Start date (UTC) inclusive, format YYYY-MM-DD",
    )
    parser.add_argument(
        "--end",
        type=_parse_date,
        help="End date (UTC) inclusive, format YYYY-MM-DD. Defaults to start date when omitted.",
    )
    parser.add_argument(
        "--base-url",
        default="https://public.bybit.com/trading",
        help="Base URL for Bybit public CSV archives",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/bybit_public"),
        help="Directory where downloaded CSV archives are cached",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(get_default_db_path()),
        help="SQLite database storing bybit_liquidations",
    )
    parser.add_argument(
        "--parquet-dir",
        type=Path,
        default=Path("data/bybit_liquidations"),
        help="Optional directory for Parquet exports (set to empty to disable)",
    )
    parser.add_argument(
        "--flush-size",
        type=int,
        default=1000,
        help="Flush writer buffer after N events (default: 1000)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count rows without writing to the database")

    args = parser.parse_args()

    end_date = args.end or args.start
    if end_date < args.start:
        parser.error("--end date must be greater or equal to --start")

    symbols = [sym.strip() for sym in args.symbols.split(",") if sym.strip()]
    parquet_dir: Path | None = args.parquet_dir if str(args.parquet_dir).strip() else None

    options = BackfillOptions(
        symbols=symbols,
        start=args.start,
        end=end_date,
        base_url=args.base_url,
        cache_dir=args.cache_dir,
        db_path=args.db,
        parquet_dir=parquet_dir,
        flush_size=args.flush_size,
        dry_run=args.dry_run,
    )

    logger.info(
        "bybit_backfill_start",
        symbols=symbols,
        start=str(args.start),
        end=str(end_date),
        dry_run=args.dry_run,
        db=str(args.db),
    )
    summary = backfill(options)
    print(json.dumps(summary, indent=2, sort_keys=True))
    logger.info("bybit_backfill_done", stats=summary["symbols"])
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())

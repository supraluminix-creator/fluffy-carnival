from __future__ import annotations

import csv
import gzip
import io
import shutil
import urllib.request
from collections.abc import Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import TypedDict, cast

import structlog

from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter
from pipeline.storage.sqlite_adapter import get_default_db_path

logger = structlog.get_logger(__name__)

_DEFAULT_BASE_URL = "https://public.bybit.com/trading"
_SUPPORTED_EXTENSIONS = {".csv", ".csv.gz", ".gz"}


@dataclass(slots=True)
class BackfillOptions:
    symbols: list[str]
    start: date
    end: date
    base_url: str = _DEFAULT_BASE_URL
    cache_dir: Path = Path("data/bybit_public")
    db_path: Path = Path(get_default_db_path())
    parquet_dir: Path | None = Path("data/bybit_liquidations")
    flush_size: int = 500
    dry_run: bool = False


def _iter_days(start: date, end: date) -> Iterator[date]:
    cur = start
    delta = timedelta(days=1)
    while cur <= end:
        yield cur
        cur += delta


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _resolve_remote_path(symbol: str, day: date) -> str:
    name = f"{symbol}{day.strftime('%Y-%m-%d')}"
    return f"{symbol}/{name}.csv.gz"


def _ensure_cache_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _download_if_needed(base_url: str, cache_dir: Path, relative_path: str) -> Path:
    target = cache_dir / relative_path
    if target.exists():
        return target
    _ensure_cache_dir(target.parent)
    url = f"{base_url.rstrip('/')}/{relative_path.lstrip('/')}"
    logger.info("bybit_backfill_download", url=url, dest=str(target))
    try:
        with urllib.request.urlopen(url, timeout=30) as response, target.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning("bybit_backfill_download_failed", url=url, error=str(exc))
        raise
    return target


def _open_csv_stream(path: Path) -> io.TextIOBase:
    suffix = path.suffix.lower()
    if suffix == ".gz" or path.name.endswith(".csv.gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
    if suffix == ".csv":
        return path.open("r", encoding="utf-8")
    raise ValueError(f"Unsupported file format: {path}")


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _ensure_milliseconds(timestamp: int) -> int:
    """Return a millisecond precision timestamp.

    Bybit's public CSV archives sometimes encode timestamps in seconds. We
    normalise to milliseconds so downstream range computations operate on a
    single unit.
    """

    if timestamp < 10_000_000_000:  # < ~Sat Nov 20 2286 when expressed in ms
        return timestamp * 1000
    return timestamp


class NormalizedRow(TypedDict):
    symbol: str
    side: str
    price: float
    qty: float
    time: int


def _normalize_row(row: dict[str, str], default_symbol: str | None = None) -> NormalizedRow | None:
    symbol = row.get("symbol") or row.get("contract") or default_symbol
    if not symbol:
        return None
    symbol_norm = _normalize_symbol(symbol)

    price = _parse_float(row.get("price"))
    qty = _parse_float(row.get("qty") or row.get("size") or row.get("volume"))
    if price is None or qty is None:
        return None

    ts_raw = row.get("timestamp") or row.get("trade_time") or row.get("updatedTime")
    ts = _parse_int(ts_raw)
    if ts is None:
        return None
    ts = _ensure_milliseconds(ts)

    side_raw = (row.get("side") or "").strip().lower()
    side = "BUY" if side_raw.startswith("b") else "SELL" if side_raw.startswith("s") else side_raw.upper()

    return cast(
        NormalizedRow,
        {
            "symbol": symbol_norm,
            "side": side,
            "price": float(price),
            "qty": float(qty),
            "time": int(ts),
        },
    )


def iter_liquidations_from_csv(path: Path, default_symbol: str | None = None) -> Iterable[NormalizedRow]:
    with _open_csv_stream(path) as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            if not isinstance(row, dict):
                continue
            record = _normalize_row(row, default_symbol)
            if record is None:
                continue
            yield record


def ingest_file(path: Path, writer: BybitLiquidationsWriter, *, default_symbol: str | None = None) -> int:
    seen: set[tuple[str, int, float, float]] = set()
    batch: list[NormalizedRow] = []
    for record in iter_liquidations_from_csv(path, default_symbol):
        key = (
            str(record["symbol"]),
            int(record["time"]),
            float(record["price"]),
            float(record["qty"]),
        )
        if key in seen:
            continue
        seen.add(key)
        batch.append(record)
    if not batch:
        return 0
    payload = (
        {
            "symbol": row["symbol"],
            "side": row["side"],
            "price": row["price"],
            "qty": row["qty"],
            "time": row["time"],
        }
        for row in batch
    )
    return writer.write_many(payload)


def backfill(options: BackfillOptions) -> dict[str, object]:
    symbols = [_normalize_symbol(sym) for sym in options.symbols]
    if not symbols:
        raise ValueError("At least one symbol required")

    results: dict[str, dict[str, int]] = {}
    if not options.dry_run:
        writer = BybitLiquidationsWriter(
            db=str(options.db_path),
            parquet_dir=str(options.parquet_dir) if options.parquet_dir else None,
            flush_size=options.flush_size,
            flush_interval=options.flush_size,
        )
    else:
        writer = None  # type: ignore[assignment]

    try:
        for symbol in symbols:
            sym_stats = {"files": 0, "rows": 0}
            for day in _iter_days(options.start, options.end):
                relative = _resolve_remote_path(symbol, day)
                local_path = options.cache_dir / relative
                if not local_path.exists():
                    try:
                        local_path = _download_if_needed(options.base_url, options.cache_dir, relative)
                    except Exception:
                        continue
                ext = "".join(local_path.suffixes)
                if not any(ext.endswith(suf) for suf in _SUPPORTED_EXTENSIONS):
                    logger.debug("bybit_backfill_skip", path=str(local_path))
                    continue
                sym_stats["files"] += 1
                if options.dry_run or writer is None:
                    sym_stats["rows"] += sum(1 for _ in iter_liquidations_from_csv(local_path, symbol))
                    continue
                written = ingest_file(local_path, writer, default_symbol=symbol)
                sym_stats["rows"] += written
                if written:
                    with suppress(RuntimeError):
                        writer.flush_sync()
            results[symbol] = sym_stats
    finally:
        if not options.dry_run and writer is not None:
            with suppress(RuntimeError):
                writer.flush_sync()
            writer.close()

    return {"symbols": results, "dry_run": options.dry_run, "db": str(options.db_path)}

__all__ = ["BackfillOptions", "backfill", "iter_liquidations_from_csv", "ingest_file"]

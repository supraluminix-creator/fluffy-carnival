from __future__ import annotations

import asyncio
import sqlite3
import time
from collections import defaultdict
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.metrics.export import (
    FLUSH_FAILURES_TOTAL,
    FLUSH_LIQ_ROWS_WRITTEN,
    FLUSH_OPERATIONS_TOTAL,
    LAST_FLUSH_DURATION_SECONDS,
    LAST_FLUSH_TIMESTAMP,
    WRITER_FLUSH_LATENCY_SECONDS,
)
from pipeline.storage.sqlite_adapter import get_default_db_path


def _ensure_dirs(path: str) -> None:
    p = Path(path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)


def _normalize_event(ev: dict[str, Any]) -> dict[str, Any]:
    sym = str(ev.get("symbol", "")).upper()
    side_raw = str(ev.get("side", "")).upper()
    side = "BUY" if side_raw.startswith("B") else ("SELL" if side_raw.startswith("S") else side_raw)
    price = float(ev.get("price", 0.0) or 0.0)
    qty = ev.get("qty")
    if qty is None:
        qty = ev.get("size")
    qty = float(qty or 0.0)
    t_ms = ev.get("time")
    if t_ms is None:
        t_ms = ev.get("updatedTime")
    if t_ms is None:
        t_ms = int(datetime.now(UTC).timestamp() * 1000)
    try:
        t_ms = int(t_ms)
    except Exception:
        t_ms = int(datetime.now(UTC).timestamp() * 1000)
    if t_ms < 10_000_000_000:
        t_ms *= 1000
    qty_usd = price * qty
    return {
        "symbol": sym,
        "side": side,
        "price": float(price),
        "qty": float(qty),
        "qty_usd": float(qty_usd),
        "time": int(t_ms),
    }


@dataclass
class BybitLiquidationsWriter:
    db: str = field(default_factory=get_default_db_path)
    parquet_dir: str | None = None
    flush_size: int = 100
    flush_interval: int = 60
    parquet_enabled: bool = False

    def __post_init__(self) -> None:
        _ensure_dirs(self.db)
        self._buffer: list[dict[str, Any]] = []
        self._conn = sqlite3.connect(self.db)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()
        self._migrate_schema()
        self._ensure_indexes()
        # Simple timer-based flushing could be added; tests call flush explicitly.

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bybit_liquidations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                qty REAL NOT NULL,
                qty_usd REAL NOT NULL,
                time INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bybit_liquidations_hourly (
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                hour_start INTEGER NOT NULL,
                total_qty_usd REAL NOT NULL,
                events_count INTEGER NOT NULL,
                PRIMARY KEY(symbol, side, hour_start)
            )
            """
        )
        self._conn.commit()

    def _migrate_schema(self) -> None:
        cur = self._conn.cursor()

        # Legacy schema lacked qty_usd column.
        cur.execute("PRAGMA table_info(bybit_liquidations)")
        columns = {row[1] for row in cur.fetchall()}
        qty_usd_added = False
        if "qty_usd" not in columns:
            cur.execute("ALTER TABLE bybit_liquidations ADD COLUMN qty_usd REAL")
            qty_usd_added = True

        # Recompute USD notionals for any row still unset or zero.
        cur.execute(
            """
            UPDATE bybit_liquidations
               SET qty_usd = price * qty
             WHERE qty_usd IS NULL OR qty_usd = 0
            """
        )

        # Normalise timestamps that were ingested with second precision.
        cur.execute("SELECT COUNT(*) FROM bybit_liquidations WHERE time < 1000000000000")
        needs_timestamp_fix = cur.fetchone()[0] > 0
        if needs_timestamp_fix:
            cur.execute(
                """
                UPDATE bybit_liquidations
                   SET time = time * 1000
                 WHERE time < 1000000000000
                """
            )

        # When upgrading from the legacy table, rebuild the hourly aggregates to include USD notionals.
        if qty_usd_added or needs_timestamp_fix:
            self._rebuild_hourly()

        self._conn.commit()

    def _rebuild_hourly(self) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM bybit_liquidations_hourly")
        cur.execute(
            """
            INSERT INTO bybit_liquidations_hourly(symbol, side, hour_start, total_qty_usd, events_count)
            SELECT symbol,
                   side,
                   (time / 1000 / 3600) * 3600 AS hour_start,
                   SUM(qty_usd) AS total_qty_usd,
                   COUNT(*) AS events_count
              FROM bybit_liquidations
             GROUP BY symbol, side, hour_start
            """
        )

    def _ensure_indexes(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_bybit_liq_symbol_time ON bybit_liquidations(symbol, time)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bybit_liq_time ON bybit_liquidations(time)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_bybit_liq_hour_symbol_side "
            "ON bybit_liquidations_hourly(hour_start, symbol, side)"
        )
        self._conn.commit()

    async def write_record(self, record: dict[str, Any]) -> None:
        rec = _normalize_event(record)
        self._buffer.append(rec)
        if len(self._buffer) >= self.flush_size:
            await self.flush()

    def write_many(self, records: Iterable[dict[str, Any]]) -> int:
        """Synchronously enqueue multiple records.

        Designed for offline backfill scripts where an event loop is not
        running; falls back to `flush_sync` when the buffer reaches the
        configured flush size.
        """

        count = 0
        for record in records:
            rec = _normalize_event(record)
            self._buffer.append(rec)
            count += 1
            if len(self._buffer) >= self.flush_size:
                self.flush_sync()
        return count

    async def flush(self) -> int:
        if not self._buffer:
            return 0
        writer_label = "bybit_liq"
        start = time.perf_counter()
        rows = self._buffer
        self._buffer = []
        cur = self._conn.cursor()
        try:
            # Insert raw
            cur.executemany(
                "INSERT INTO bybit_liquidations(symbol, side, price, qty, qty_usd, time) VALUES(?,?,?,?,?,?)",
                [(r["symbol"], r["side"], r["price"], r["qty"], r["qty_usd"], r["time"]) for r in rows],
            )
            # Aggregate by hour
            agg: dict[tuple[str, str, int], tuple[float, int]] = defaultdict(lambda: (0.0, 0))
            for r in rows:
                hour_start = (r["time"] // 1000) // 3600 * 3600
                key = (r["symbol"], r["side"], hour_start)
                s, c = agg[key]
                agg[key] = (s + float(r["qty_usd"]), c + 1)
            for (sym, side, hour_start), (total, count) in agg.items():
                # Upsert into hourly
                cur.execute(
                    """
                    INSERT INTO bybit_liquidations_hourly(symbol, side, hour_start, total_qty_usd, events_count)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, side, hour_start) DO UPDATE SET
                        total_qty_usd = total_qty_usd + excluded.total_qty_usd,
                        events_count = events_count + excluded.events_count
                    """,
                    (sym, side, hour_start, float(total), int(count)),
                )
            self._conn.commit()

            # Optional parquet step
            if self.parquet_enabled and self.parquet_dir:
                try:
                    import pandas as pd  # pandas is optional at runtime

                    out_dir = Path(self.parquet_dir)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    df = pd.DataFrame(rows)
                    out_path = out_dir / "batch.parquet"
                    df.to_parquet(out_path, index=False)
                except Exception:
                    dur = time.perf_counter() - start
                    try:
                        WRITER_FLUSH_LATENCY_SECONDS.labels(writer=writer_label, status="error").observe(dur)
                        FLUSH_OPERATIONS_TOTAL.labels(writer=writer_label, status="error").inc()
                        FLUSH_FAILURES_TOTAL.labels(writer=writer_label, phase="write").inc()
                    except Exception:
                        pass
                    # Do not raise to allow tests to inspect metrics
                    return len(rows)

            # Success metrics (either parquet disabled or write ok)
            dur = time.perf_counter() - start
            try:
                WRITER_FLUSH_LATENCY_SECONDS.labels(writer=writer_label, status="success").observe(dur)
                FLUSH_OPERATIONS_TOTAL.labels(writer=writer_label, status="success").inc()
                LAST_FLUSH_TIMESTAMP.labels(writer=writer_label).set(time.time())
                LAST_FLUSH_DURATION_SECONDS.labels(writer=writer_label).set(dur)
                FLUSH_LIQ_ROWS_WRITTEN.labels(writer=writer_label).inc(len(rows))
            except Exception:
                pass
            return len(rows)
        except Exception:
            dur = time.perf_counter() - start
            try:
                WRITER_FLUSH_LATENCY_SECONDS.labels(writer=writer_label, status="error").observe(dur)
                FLUSH_OPERATIONS_TOTAL.labels(writer=writer_label, status="error").inc()
                FLUSH_FAILURES_TOTAL.labels(writer=writer_label, phase="write").inc()
            except Exception:
                pass
            return 0

    def close(self) -> None:
        with suppress(Exception):
            self._conn.close()

    def flush_sync(self) -> int:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            raise RuntimeError("flush_sync cannot run inside a running event loop")
        return asyncio.run(self.flush())


__all__ = ["BybitLiquidationsWriter"]

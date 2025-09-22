"""Bybit liquidation events writer (async buffer -> SQLite + optional Parquet).

This version normalise incoming events and maintains both a raw events table and
an hourly aggregate table. Safe for concurrent async writes using an asyncio.Lock.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, UTC
from typing import Any, Mapping, List, TypedDict

import pandas as pd

try:  # pragma: no cover - si metrics indisponible
    from pipeline.metrics import BUFFER_LENGTH, LAST_FLUSH_TIMESTAMP, FLUSH_OPERATIONS_TOTAL, FLUSH_FAILURES_TOTAL, WRITER_FLUSH_LATENCY_SECONDS
except Exception:  # pragma: no cover
    BUFFER_LENGTH = LAST_FLUSH_TIMESTAMP = FLUSH_OPERATIONS_TOTAL = FLUSH_FAILURES_TOTAL = WRITER_FLUSH_LATENCY_SECONDS = None  # type: ignore

logger = logging.getLogger(__name__)


class LiquidationRecord(TypedDict):
    symbol: str
    side: str
    price: float
    qty: float
    time: int  # epoch ms


class BybitLiquidationsWriter:
    def __init__(
        self,
        db: str = "data/crypto.db",
        parquet_dir: str = "data/bybit_liquidations",
        flush_size: int = 100,
        flush_interval: int = 5,
        parquet_enabled: bool = True,
    ) -> None:
        self.db: str = db
        self.parquet_dir: str = parquet_dir
        self.flush_size: int = flush_size
        self.flush_interval: int = flush_interval
        self.parquet_enabled: bool = parquet_enabled

        os.makedirs(os.path.dirname(db), exist_ok=True)
        os.makedirs(parquet_dir, exist_ok=True)

        from pipeline.storage.sqlite_adapter import get_connection
        self.conn = get_connection(self.db)
        self._create_tables()

        self.buffer: List[LiquidationRecord] = []
        # Utilise datetime.now(UTC) pour éviter DeprecationWarning
        self.last_flush: float = datetime.now(UTC).timestamp()
        self.lock: asyncio.Lock = asyncio.Lock()

        logger.info(
            "BybitLiquidationsWriter initialized (db=%s parquet=%s parquet_enabled=%s)",
            db,
            parquet_dir,
            parquet_enabled,
        )

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        cur = self.conn.cursor()
        
        # Raw liquidations table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bybit_liquidations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            qty REAL NOT NULL,
            time INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Hourly aggregates table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bybit_liquidations_hourly (
            hour_start INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            total_qty_usd REAL NOT NULL DEFAULT 0,
            events_count INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (hour_start, symbol, side)
        )
        """)
        
        # Create indexes for performance
        cur.execute("CREATE INDEX IF NOT EXISTS idx_liquidations_time ON bybit_liquidations(time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_liquidations_symbol ON bybit_liquidations(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_hourly_time ON bybit_liquidations_hourly(hour_start)")
        
        self.conn.commit()
        logger.info("Database tables created/verified")

    # -----------------------------------------------------
    # RECORD WRITE
    # -----------------------------------------------------
    async def write_record(self, record: Mapping[str, Any]) -> None:
        async with self.lock:
            try:
                # Extract data from Bybit liquidation message format
                symbol_raw = record.get("symbol")
                side_raw = record.get("side", "UNKNOWN")
                price_val = record.get("price", 0)
                size_val = record.get("size", 0)  # Bybit uses "size" not "qty"
                ts_val = record.get("updatedTime", record.get("ts", datetime.now(UTC).timestamp() * 1000))

                try:
                    price = float(price_val)
                    size = float(size_val)
                    ts = int(ts_val)
                except (TypeError, ValueError):
                    return
                symbol = (str(symbol_raw) if symbol_raw else "").upper()
                side = str(side_raw).upper()

                if not symbol or price == 0 or size == 0:
                    logger.debug("Skipping invalid record: symbol=%s price=%s size=%s", symbol, price, size)
                    return

                rec: LiquidationRecord = {
                    "symbol": symbol,
                    "side": side,
                    "price": price,
                    "qty": size,
                    "time": ts,
                }
                self.buffer.append(rec)
                if BUFFER_LENGTH is not None:
                    try:
                        BUFFER_LENGTH.labels(writer="bybit_liq").set(len(self.buffer))
                    except Exception:  # pragma: no cover - defensive
                        pass

                logger.debug("Buffered liquidation: %s %s %.3f @ $%.2f", symbol, side, size, price)

                now = datetime.now(UTC).timestamp()
                if len(self.buffer) >= self.flush_size or (now - self.last_flush) >= self.flush_interval:  # pragma: no cover - timing précis non déterministe test
                    await self.flush()

            except Exception as e:
                logger.error("Error parsing record: %s | record: %s", e, record, exc_info=True)

    # -----------------------------------------------------
    # FLUSH
    # -----------------------------------------------------
    async def flush(self) -> None:
        if not self.buffer:
            if FLUSH_OPERATIONS_TOTAL is not None:
                try:
                    FLUSH_OPERATIONS_TOTAL.labels(writer="bybit_liq", status="noop").inc()
                except Exception:  # pragma: no cover
                    pass
            return

        start_time = datetime.now(UTC).timestamp()
        buf = self.buffer
        self.buffer = []
        self.last_flush = datetime.now(UTC).timestamp()

        logger.info("Flushing %d liquidation events to database", len(buf))

        try:
            df = pd.DataFrame(buf)
            if df.empty:  # pragma: no cover - buffer vide déjà filtré
                return

            cur = self.conn.cursor()
            cur.executemany("""
            INSERT INTO bybit_liquidations (symbol, side, price, qty, time)
            VALUES (?, ?, ?, ?, ?)
            """, [(r["symbol"], r["side"], r["price"], r["qty"], r["time"]) for _, r in df.iterrows()])

            for _, r in df.iterrows():
                hour_start = int(r["time"] // 1000 // 3600 * 3600)
                cur.execute("""
                INSERT INTO bybit_liquidations_hourly (hour_start, symbol, side, total_qty_usd, events_count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(hour_start, symbol, side)
                DO UPDATE SET total_qty_usd = total_qty_usd + ?, events_count = events_count + 1
                """, (hour_start, r["symbol"], r["side"], r["price"] * r["qty"], r["price"] * r["qty"]))

            self.conn.commit()
            logger.info("Successfully flushed %d events to database", len(buf))
            if FLUSH_OPERATIONS_TOTAL is not None:
                try:
                    FLUSH_OPERATIONS_TOTAL.labels(writer="bybit_liq", status="success").inc()
                    LAST_FLUSH_TIMESTAMP.labels(writer="bybit_liq").set(self.last_flush)
                    BUFFER_LENGTH.labels(writer="bybit_liq").set(0)
                except Exception:  # pragma: no cover
                    pass

            if self.parquet_enabled:  # pragma: no cover
                last_ts_ms = int(df.iloc[-1]["time"]) if not df.empty else int(datetime.now(UTC).timestamp() * 1000)
                dt = datetime.fromtimestamp(last_ts_ms / 1000, tz=UTC)
                part_dir = os.path.join(
                    self.parquet_dir,
                    f"year={dt.year}",
                    f"month={dt.month:02d}",
                    f"day={dt.day:02d}",
                    f"hour={dt.hour:02d}",
                )
                os.makedirs(part_dir, exist_ok=True)
                parquet_path = os.path.join(part_dir, "bybit_liquidations.parquet")
                df.to_parquet(parquet_path, index=False, engine="pyarrow")
                logger.debug("Flushed to parquet partitioned: %s", parquet_path)

            if WRITER_FLUSH_LATENCY_SECONDS is not None:
                try:
                    WRITER_FLUSH_LATENCY_SECONDS.labels(writer="bybit_liq", status="success").observe(datetime.now(UTC).timestamp() - start_time)
                except Exception:  # pragma: no cover
                    pass

        except Exception as e:  # pragma: no cover - erreur flush
            logger.error("Error during flush: %s", e, exc_info=True)
            if FLUSH_FAILURES_TOTAL is not None:
                try:
                    FLUSH_FAILURES_TOTAL.labels(writer="bybit_liq", phase="write").inc()
                except Exception:
                    pass
            if WRITER_FLUSH_LATENCY_SECONDS is not None:
                try:
                    WRITER_FLUSH_LATENCY_SECONDS.labels(writer="bybit_liq", status="error").observe(datetime.now(UTC).timestamp() - start_time)
                except Exception:
                    pass

    async def close(self) -> None:
        await self.flush()  # pragma: no cover - flush final
        self.conn.close()  # pragma: no cover - fermeture non critique

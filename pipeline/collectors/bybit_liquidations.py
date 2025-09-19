"""
Bybit Liquidations Writer (prod-safe)
- Ecrit en SQLite (événements + agrégats horaires)
- Flush vers Parquet (optionnel)
- Utilisé par bybit_ws.py
"""

import asyncio
import logging
import os
import sqlite3
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)


class BybitLiquidationsWriter:
    def __init__(self, db="data/crypto.db", parquet_dir="data/bybit_liquidations",
                 flush_size=100, flush_interval=5, parquet_enabled=True):
        self.db = db
        self.parquet_dir = parquet_dir
        self.flush_size = flush_size
        self.flush_interval = flush_interval
        self.parquet_enabled = parquet_enabled

        os.makedirs(os.path.dirname(db), exist_ok=True)
        os.makedirs(parquet_dir, exist_ok=True)

        self.conn = sqlite3.connect(self.db, check_same_thread=False)
        self._create_tables()

        self.buffer = []
        self.last_flush = datetime.utcnow().timestamp()
        self.lock = asyncio.Lock()

        logger.info(
            "BybitLiquidationsWriter initialized (db=%s parquet=%s parquet_enabled=%s)",
            db, parquet_dir, parquet_enabled
        )

    def _create_tables(self):
        """Create database tables if they don't exist"""
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
    async def write_record(self, record):
        async with self.lock:
            try:
                # Extract data from Bybit liquidation message format
                symbol = record.get("symbol", "")
                side = record.get("side", "UNKNOWN")
                price = float(record.get("price", 0))
                size = float(record.get("size", 0))  # Bybit uses "size" not "qty"
                ts = int(record.get("updatedTime", record.get("ts", datetime.utcnow().timestamp() * 1000)))

                if not symbol or price == 0 or size == 0:
                    logger.debug("Skipping invalid record: symbol=%s price=%s size=%s", symbol, price, size)
                    return

                self.buffer.append({
                    "symbol": symbol.upper(),
                    "side": side.upper(),
                    "price": price,
                    "qty": size,  # Store as qty for consistency
                    "time": ts
                })

                logger.debug("Buffered liquidation: %s %s %.3f @ $%.2f", symbol, side, size, price)

                now = datetime.utcnow().timestamp()
                if len(self.buffer) >= self.flush_size or (now - self.last_flush) >= self.flush_interval:
                    await self.flush()

            except Exception as e:
                logger.error("Error parsing record: %s | record: %s", e, record, exc_info=True)

    # -----------------------------------------------------
    # FLUSH
    # -----------------------------------------------------
    async def flush(self):
        if not self.buffer:
            return

        buf = self.buffer
        self.buffer = []
        self.last_flush = datetime.utcnow().timestamp()

        logger.info("Flushing %d liquidation events to database", len(buf))

        try:
            df = pd.DataFrame(buf)
            if df.empty:
                return

            # SQLite: raw events
            cur = self.conn.cursor()
            cur.executemany("""
            INSERT INTO bybit_liquidations (symbol, side, price, qty, time)
            VALUES (?, ?, ?, ?, ?)
            """, [(r["symbol"], r["side"], r["price"], r["qty"], r["time"]) for _, r in df.iterrows()])

            # SQLite: aggregates
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

            # Parquet flush (optional)
            if self.parquet_enabled:
                parquet_path = os.path.join(self.parquet_dir, f"bybit_liquidations_{datetime.utcnow().strftime('%Y%m%d_%H')}.parquet")
                df.to_parquet(parquet_path, index=False, engine="pyarrow")
                logger.debug("Flushed to parquet: %s", parquet_path)

        except Exception as e:
            logger.error("Error during flush: %s", e, exc_info=True)

    async def close(self):
        await self.flush()
        self.conn.close()

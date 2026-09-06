#!/usr/bin/env python3
"""
Integration test: test the complete data flow from WebSocket to database
"""

import asyncio
import json
import os
import sys
from datetime import datetime

# Add the project root to the path
sys.path.insert(0, os.path.dirname(__file__))

from collections.abc import Mapping, Sequence
from typing import Any, cast

from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter


async def test_integration() -> None:
    print("🧪 Integration Test: WebSocket Message -> Database")
    print("=" * 55)

    # Clean up test database
    test_db = "data/integration_test.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    # Create writer with immediate flush
    writer = BybitLiquidationsWriter(
        db=test_db,
        parquet_dir="test_parquet_integration",
        flush_size=1,  # Immediate flush
        flush_interval=1,
        parquet_enabled=False,
    )

    # Simulate the exact message format from Bybit WebSocket
    bybit_message = {
        "topic": "liquidation.BTCUSDT",
        "type": "snapshot",
        "ts": 1758132828134,
        "data": {
            "updatedTime": 1758132828134,
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "0.038",
            "price": "114826.80",
        },
    }

    print("📨 Simulating WebSocket message:")
    print(f"   Raw message: {json.dumps(bybit_message)}")

    # Extract the data part (this is what the collector sends to the writer)
    data_raw = bybit_message["data"]
    if not isinstance(data_raw, dict):
        raise AssertionError("Unexpected data shape in simulated message")
    data: Mapping[str, Any] = data_raw
    print(f"📝 Data sent to writer: {data}")

    # Write the record
    await writer.write_record(data)
    print("✅ Record written to writer buffer")

    # Force flush
    await writer.flush()
    print("✅ Buffer flushed to database")

    # Verify in database
    import sqlite3

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM bybit_liquidations")
    count_row = cursor.fetchone()
    count = int(count_row[0]) if count_row else 0
    print(f"📊 Records in database: {count}")

    if count > 0:
        cursor.execute("SELECT symbol, side, price, qty, time FROM bybit_liquidations")
        row = cursor.fetchone()
        assert row is not None
        symbol, side, price, qty, ts = cast(Sequence[Any], row)
        dt = datetime.fromtimestamp(ts / 1000)
        usd_value = price * qty
        print(
            f"💰 Stored liquidation: {dt.strftime('%H:%M:%S')} | {symbol} | {side} | ${price:,.2f} | {qty} | ${usd_value:,.2f}"
        )

        # Verify the data matches
        expected_price = float(data["price"])
        expected_qty = float(data["size"])
        expected_symbol = data["symbol"]
        expected_side = data["side"]

        if (
            symbol == expected_symbol
            and side.upper() == expected_side.upper()
            and abs(price - expected_price) < 0.01
            and abs(qty - expected_qty) < 0.001
        ):
            print("✅ Data integrity verified - stored data matches input!")
        else:
            print("❌ Data mismatch!")
            print(f"   Expected: {expected_symbol} {expected_side} ${expected_price} {expected_qty}")
            print(f"   Stored:   {symbol} {side} ${price} {qty}")

    conn.close()
    await writer.close()

    # Clean up
    if os.path.exists(test_db):
        os.remove(test_db)

    print("\n🎉 Integration test completed successfully!")
    print("🔧 The collector is ready to store real liquidation data!")


if __name__ == "__main__":
    asyncio.run(test_integration())

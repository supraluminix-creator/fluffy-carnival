#!/usr/bin/env python3
"""
Test script for BybitLiquidationsWriter
Simulates liquidation events and verifies database storage
"""
import asyncio
import os
import sqlite3
import sys
from datetime import datetime

# Add the project root to the path so we can import the modules
sys.path.insert(0, os.path.dirname(__file__))

from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter


async def test_writer():
    print("🧪 Testing BybitLiquidationsWriter...")
    
    # Clean up any existing test database
    test_db = "data/test_crypto.db"
    if os.path.exists(test_db):
        os.remove(test_db)
    
    # Create writer
    writer = BybitLiquidationsWriter(
        db=test_db,
        parquet_dir="test_parquet",
        flush_size=2,  # Small flush size for testing
        flush_interval=1,
        parquet_enabled=False
    )
    
    # Test liquidation events in the format we receive from Bybit
    test_events = [
        {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "0.038",
            "price": "114826.80",
            "updatedTime": 1758132828134
        },
        {
            "symbol": "ETHUSDT", 
            "side": "Sell",
            "size": "2.15", 
            "price": "4488.54",
            "updatedTime": 1758132829000
        },
        {
            "symbol": "BTCUSDT",
            "side": "Buy", 
            "size": "0.983",
            "price": "114387.70",
            "updatedTime": 1758132830000
        }
    ]
    
    print(f"📝 Writing {len(test_events)} test events...")
    
    for i, event in enumerate(test_events):
        await writer.write_record(event)
        print(f"  Event {i+1}: {event['symbol']} {event['side']} {event['size']} @ ${event['price']}")
    
    # Force flush
    await writer.flush()
    
    # Verify data in database
    print("\n🔍 Verifying database content...")
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    
    # Check tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [t[0] for t in cursor.fetchall()]
    print(f"✅ Tables created: {tables}")
    
    # Check raw data
    cursor.execute("SELECT COUNT(*) FROM bybit_liquidations")
    count = cursor.fetchone()[0]
    print(f"✅ Raw liquidations stored: {count}")
    
    if count > 0:
        cursor.execute("SELECT symbol, side, price, qty, time FROM bybit_liquidations ORDER BY time")
        rows = cursor.fetchall()
        print("📊 Raw data:")
        for row in rows:
            symbol, side, price, qty, ts = row
            dt = datetime.fromtimestamp(ts/1000)
            usd_value = price * qty
            print(f"  {dt.strftime('%H:%M:%S')} | {symbol} | {side:4} | ${price:8,.2f} | {qty:8.3f} | ${usd_value:10,.2f}")
    
    # Check hourly aggregates
    cursor.execute("SELECT COUNT(*) FROM bybit_liquidations_hourly")
    hourly_count = cursor.fetchone()[0]
    print(f"✅ Hourly aggregates: {hourly_count}")
    
    if hourly_count > 0:
        cursor.execute("SELECT hour_start, symbol, side, total_qty_usd, events_count FROM bybit_liquidations_hourly")
        hourly_rows = cursor.fetchall()
        print("📈 Hourly aggregates:")
        for row in hourly_rows:
            hour_start, symbol, side, total_usd, events = row
            dt = datetime.fromtimestamp(hour_start)
            print(f"  {dt.strftime('%Y-%m-%d %H:00')} | {symbol} | {side:4} | ${total_usd:10,.2f} | {events} events")
    
    conn.close()
    await writer.close()
    
    print(f"\n✅ Test completed! Database: {test_db}")
    print("🧹 Cleaning up test files...")
    
    # Clean up
    if os.path.exists(test_db):
        os.remove(test_db)
    if os.path.exists("test_parquet") and os.path.isdir("test_parquet"):
        import shutil
        shutil.rmtree("test_parquet")
    
    print("✨ Test completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_writer())
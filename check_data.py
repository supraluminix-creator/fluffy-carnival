#!/usr/bin/env python3
"""
Data verification script for Bybit liquidations collector
Check what data was collected overnight
"""
import os
import sqlite3
from datetime import datetime


def check_database():
    """Check SQLite database for liquidation data"""
    db_path = "data/crypto.db"
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return
    
    print(f"✅ Database found: {db_path}")
    print(f"📊 Database size: {os.path.getsize(db_path):,} bytes")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"\n📋 Tables in database: {[t[0] for t in tables]}")
        
        # Check bybit_liquidations table if it exists
        if any('bybit_liquidations' in t[0] for t in tables):
            # Raw events
            cursor.execute("SELECT COUNT(*) FROM bybit_liquidations")
            count = cursor.fetchone()[0]
            print(f"📈 Total liquidation events: {count:,}")
            
            if count > 0:
                # Latest events
                cursor.execute("""
                SELECT symbol, side, price, qty, time 
                FROM bybit_liquidations 
                ORDER BY time DESC 
                LIMIT 10
                """)
                latest = cursor.fetchall()
                print("\n🔥 Latest 10 liquidations:")
                for row in latest:
                    symbol, side, price, qty, ts = row
                    dt = datetime.fromtimestamp(ts/1000)
                    usd_value = price * qty
                    print(
                        f"  {dt.strftime('%H:%M:%S')} | {symbol} | {side:4} | "
                        f"${price:8,.2f} | {qty:8.3f} | ${usd_value:10,.2f}"
                    )
                
                # Summary by symbol
                cursor.execute("""
                SELECT symbol, side, COUNT(*) as events, 
                       SUM(price * qty) as total_usd,
                       AVG(price * qty) as avg_usd
                FROM bybit_liquidations 
                GROUP BY symbol, side 
                ORDER BY total_usd DESC
                """)
                summary = cursor.fetchall()
                print("\n📊 Summary by symbol and side:")
                print("Symbol    | Side | Events | Total USD     | Avg USD")
                print("-" * 55)
                for row in summary:
                    symbol, side, events, total_usd, avg_usd = row
                    print(f"{symbol:8} | {side:4} | {events:6,} | ${total_usd:11,.2f} | ${avg_usd:8,.2f}")
        
        # Check hourly aggregates if they exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%hourly%';")
        hourly_tables = cursor.fetchall()
        if hourly_tables:
            for table in hourly_tables:
                table_name = table[0]
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                print(f"\n📅 {table_name}: {count:,} hourly records")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error checking database: {e}")

def check_parquet_files():
    """Check Parquet files if any were created"""
    parquet_dir = "data/bybit_liquidations"
    
    if not os.path.exists(parquet_dir):
        print(f"\n❌ Parquet directory not found: {parquet_dir}")
        return
    
    files = [f for f in os.listdir(parquet_dir) if f.endswith('.parquet')]
    if not files:
        print("\n📁 Parquet directory exists but no files found")
        return
    
    print(f"\n📦 Parquet files found: {len(files)}")
    total_size = 0
    for file in files:
        file_path = os.path.join(parquet_dir, file)
        size = os.path.getsize(file_path)
        total_size += size
        print(f"  {file}: {size:,} bytes")
    
    print(f"📊 Total parquet data: {total_size:,} bytes")

def main():
    print("🔍 Bybit Liquidations Data Verification")
    print("=" * 50)
    
    check_database()
    check_parquet_files()
    
    print("\n✨ Data verification complete!")

if __name__ == "__main__":
    main()
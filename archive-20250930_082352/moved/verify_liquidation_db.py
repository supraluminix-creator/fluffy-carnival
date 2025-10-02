import os
import sqlite3
import time
from contextlib import suppress


def wait_for_db_and_check(db_path, timeout=10):
    """
    Wait for the DB file to appear, then check for Bybit liquidation rows.
    """
    start = time.time()
    while not os.path.exists(db_path):
        if time.time() - start > timeout:
            print(f"Timeout: {db_path} not found after {timeout}s")
            return False
        time.sleep(0.5)
    # Wait for data to be written
    for _ in range(int(timeout * 2)):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT * FROM bybit_liquidations")
            rows = cur.fetchall()
            if rows:
                print(f"Found {len(rows)} liquidation rows:")
                for row in rows:
                    print(row)
                return True
        except Exception:
            pass
        finally:
            with suppress(Exception):
                conn.close()
        time.sleep(0.5)
    print("No liquidation rows found in DB after waiting.")
    return False

if __name__ == "__main__":
    db_path = "data/crypto.db"
    wait_for_db_and_check(db_path)

from __future__ import annotations

import csv
import os
from typing import Any


def save_to_csv(rows: list[dict[str, Any]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write("")
        return
    fieldnames = sorted({k for r in rows for k in r})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def save_to_parquet(rows: list[dict[str, Any]], path: str) -> None:
    import pandas as pd  # type: ignore

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_parquet(path, index=False)


def save_to_sqlite(rows: list[dict[str, Any]], path: str, table: str = "metrics") -> None:
    import sqlite3

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not rows:
        # créer fichier vide + une table minimale
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS [{table}] ("
                "timestamp INTEGER, "
                "symbol TEXT, "
                "source TEXT, "
                "metric TEXT, "
                "value TEXT)"
            )
            conn.commit()
        finally:
            conn.close()
        return
    cols = sorted({k for r in rows for k in r})
    placeholders = ",".join(["?"] * len(cols))
    colspec = ",".join([f"[{c}]" for c in cols])
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"CREATE TABLE IF NOT EXISTS [{table}] ({colspec})")
        conn.executemany(
            f"INSERT INTO [{table}] ({colspec}) VALUES ({placeholders})",
            [[r.get(c) for c in cols] for r in rows],
        )
        conn.commit()
    finally:
        conn.close()

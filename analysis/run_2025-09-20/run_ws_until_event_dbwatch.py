import asyncio
import contextlib
import json
import os
import sqlite3
import time
from datetime import UTC, datetime

from prometheus_client import start_http_server

from pipeline.collectors.bybit_ws import (
    BYBIT_WS_CONNECTIONS,
    BYBIT_WS_ERRORS,
    BYBIT_WS_EVENTS,
    BybitWSService,
)

ARTIFACT_DIR = "analysis/run_2025-09-20/artifacts"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

DB_PATH = "data/crypto.db"

SYMBOLS_DEFAULT = [
    "BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","BNBUSDT",
    "ADAUSDT","LINKUSDT","AVAXUSDT","MATICUSDT","LTCUSDT","OPUSDT"
]

async def run_ws_until_event_dbwatch(symbols=None, max_duration=900, min_db_rows=1, poll_interval=5):
    symbols = symbols or SYMBOLS_DEFAULT
    with contextlib.suppress(Exception):
        start_http_server(8022)

    svc = BybitWSService(symbols, flush_interval=10, flush_size=200)
    start_time = time.time()

    def _extract_val(counter_obj):
        val = getattr(counter_obj, "_value", 0)
        try:
            return int(val.get())  # type: ignore[attr-defined]
        except Exception:
            try:
                return int(val)
            except Exception:
                return 0

    async def db_poll():
        # Wait for writer flushes; table may not exist initially
        while True:
            await asyncio.sleep(poll_interval)
            elapsed = time.time() - start_time
            rows = 0
            try:
                if os.path.exists(DB_PATH):
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.row_factory = sqlite3.Row
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'bybit_liquidations%'"
                        )
                        tables = [r[0] for r in cur.fetchall()]
                        if 'bybit_liquidations' in tables:
                            cur.execute("SELECT COUNT(*) FROM bybit_liquidations")
                            rows = cur.fetchone()[0]
            except Exception:
                # Ignore transient locking or race conditions
                pass
            if rows >= min_db_rows or elapsed >= max_duration:
                await svc.stop()
                break

    run_task = asyncio.create_task(svc.run())
    poll_task = asyncio.create_task(db_poll())
    await asyncio.gather(run_task, poll_task)
    elapsed = time.time() - start_time

    # Collect per-symbol events metrics even si 0
    per_symbol = {}
    try:
        for labels, metric in getattr(BYBIT_WS_EVENTS, "_metrics", {}).items():  # type: ignore[attr-defined]
            if isinstance(labels, tuple) and labels:
                per_symbol[labels[0]] = int(getattr(metric, "_value", 0))
    except Exception:
        pass

    # Final DB row count
    final_rows = 0
    try:
        if os.path.exists(DB_PATH):
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM bybit_liquidations")
                final_rows = cur.fetchone()[0]
    except Exception:
        pass

    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "connections_total": _extract_val(BYBIT_WS_CONNECTIONS),
        "errors_total": _extract_val(BYBIT_WS_ERRORS),
        "events_per_symbol": per_symbol,
        "symbols": symbols,
        "db_rows_liquidations": final_rows,
        "min_db_rows_target": min_db_rows,
        "max_duration_seconds": max_duration,
    }

    out_path = os.path.join(ARTIFACT_DIR, "ws_until_event_dbwatch_summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("WS until-event DB watch summary saved:", summary)

if __name__ == '__main__':
    asyncio.run(run_ws_until_event_dbwatch())

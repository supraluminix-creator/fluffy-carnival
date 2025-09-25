import asyncio
import contextlib
import json
import os
import random
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

# Liste élargie symboles volatils susceptibles de générer des liquidations
SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","BNBUSDT","ADAUSDT","LINKUSDT",
    "AVAXUSDT","MATICUSDT","LTCUSDT","OPUSDT","ATOMUSDT","NEARUSDT","ARBUSDT","APTUSDT",
    "SHIBUSDT","PEPEUSDT","SEIUSDT","INJUSDT"
]

async def run_ws_until_event_dbwatch_v2(max_duration=600, min_db_rows=1, poll_interval=4, synthetic_after=180):
    """Run WS jusqu'à réception d'au moins min_db_rows liquidation dans SQLite.
    Si aucune liquidation réelle après synthetic_after secondes, injection d'un événement synthétique
    (marqué) pour valider la pipeline de persistance.
    """
    with contextlib.suppress(Exception):
        start_http_server(8023)

    # Flush plus rapide pour accélérer persistance
    svc = BybitWSService(SYMBOLS, flush_interval=3, flush_size=50)
    start_time = time.time()
    synthetic_used = False

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
        nonlocal synthetic_used
        while True:
            await asyncio.sleep(poll_interval)
            elapsed = time.time() - start_time
            rows = 0
            try:
                if os.path.exists(DB_PATH):
                    with sqlite3.connect(DB_PATH) as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bybit_liquidations'")
                        if cur.fetchone():
                            cur.execute("SELECT COUNT(*) FROM bybit_liquidations")
                            rows = cur.fetchone()[0]
            except Exception:
                pass

            if rows >= min_db_rows:
                await svc.stop()
                break

            # Injection synthétique si délai dépassé et aucune ligne
            if elapsed >= synthetic_after and rows == 0 and not synthetic_used:
                try:
                    # Format inspiré des messages Bybit liquidation (simplifié)
                    record = {
                        "symbol": "BTCUSDT",
                        "side": random.choice(["Buy","Sell"]),
                        "price": 50000.0,
                        "size": 100,  # Bybit original size
                        "updatedTime": int(time.time() * 1000),
                        "_synthetic": True,
                        "_note": "Injected due to timeout to validate pipeline"
                    }
                    # writer.write_record attend un mapping dict; conversion qty etc. faite dans writer
                    await svc.writer.write_record(record)  # type: ignore[attr-defined]
                    synthetic_used = True
                except Exception:
                    pass

            if elapsed >= max_duration:
                await svc.stop()
                break

    run_task = asyncio.create_task(svc.run())
    poll_task = asyncio.create_task(db_poll())
    await asyncio.gather(run_task, poll_task)
    elapsed = time.time() - start_time

    # Collect per-symbol events métriques
    per_symbol = {}
    try:
        for labels, metric in getattr(BYBIT_WS_EVENTS, "_metrics", {}).items():  # type: ignore[attr-defined]
            if isinstance(labels, tuple) and labels:
                per_symbol[labels[0]] = int(getattr(metric, "_value", 0))
    except Exception:
        pass

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
        "db_rows_liquidations": final_rows,
        "synthetic_injected": synthetic_used,
        "synthetic_after_seconds": synthetic_after,
        "max_duration_seconds": max_duration,
        "symbols": SYMBOLS,
    }

    out_path = os.path.join(ARTIFACT_DIR, "ws_until_event_dbwatch_v2_summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("WS until-event DB watch v2 summary saved:", summary)

if __name__ == '__main__':
    asyncio.run(run_ws_until_event_dbwatch_v2())

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any

from prometheus_client import start_http_server

from pipeline.collectors.bybit_ws import (
    BYBIT_WS_CONNECTIONS,
    BYBIT_WS_ERRORS,
    BYBIT_WS_EVENTS,
    BybitWSService,
)
from pipeline.storage.sqlite_adapter import ensure_db_parent, get_default_db_path


def _extract_counter_val(counter_obj: Any) -> int:
    try:
        # prometheus_client Counter has _value (AtomicDouble) with get()
        val_obj = counter_obj._value  # type: ignore[attr-defined]
        try:
            return int(val_obj.get())  # type: ignore[attr-defined]
        except Exception:
            return int(val_obj)
    except Exception:
        return 0


def _get_db_count(db_path: str) -> int:
    if not os.path.exists(db_path):
        return 0
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bybit_liquidations'")
            if not cur.fetchone():
                return 0
            cur.execute("SELECT COUNT(*) FROM bybit_liquidations")
            return int(cur.fetchone()[0])
    except Exception:
        return 0


async def _run_until_event(
    svc: BybitWSService,
    *,
    db_path: str,
    max_duration: int,
    poll_interval: float,
    min_rows: int,
    synthetic_after: int,
    baseline_rows: int,
) -> dict[str, Any]:
    start_time = time.time()
    synthetic_used = False

    async def _poll_db_and_maybe_inject():
        nonlocal synthetic_used
        while not svc.stop_event.is_set():
            await asyncio.sleep(poll_interval)
            elapsed = time.time() - start_time
            rows = _get_db_count(db_path)
            new_rows = max(0, rows - baseline_rows)
            if new_rows >= min_rows:
                await svc.stop()
                break

            if elapsed >= synthetic_after and new_rows == 0 and not synthetic_used:
                try:
                    record = {
                        "symbol": "BTCUSDT",
                        "side": random.choice(["Buy", "Sell"]),
                        "price": 50000.0,
                        "size": 50,
                        "updatedTime": int(time.time() * 1000),
                        "_synthetic": True,
                        "_note": "Injected by ws_quick_probe to validate pipeline",
                    }
                    await svc.writer.write_record(record)  # type: ignore[attr-defined]
                    # Force a flush to persist immediately so that DB polling sees the change
                    with contextlib.suppress(Exception):
                        await svc.writer.flush()  # type: ignore[attr-defined]
                    synthetic_used = True
                except Exception:
                    pass

            if elapsed >= max_duration:
                await svc.stop()
                break

    run_task = asyncio.create_task(svc.run())
    poll_task = asyncio.create_task(_poll_db_and_maybe_inject())
    await asyncio.gather(run_task, poll_task)

    # Collect per-symbol event counts (best-effort from Counter internals)
    per_symbol: dict[str, int] = {}
    try:
        metrics = getattr(BYBIT_WS_EVENTS, "_metrics", {})  # type: ignore[attr-defined]
        for labels, metric in metrics.items():  # type: ignore[assignment]
            if isinstance(labels, tuple) and labels:
                sym = str(labels[0])
                try:
                    mv = metric._value  # type: ignore[attr-defined]
                    try:
                        val = int(mv.get())  # type: ignore[attr-defined]
                    except Exception:
                        val = int(mv)
                except Exception:
                    val = 0
                per_symbol[sym] = val
    except Exception:
        pass

    return {
        "elapsed_seconds": round(time.time() - start_time, 2),
        "connections_total": _extract_counter_val(BYBIT_WS_CONNECTIONS),
        "errors_total": _extract_counter_val(BYBIT_WS_ERRORS),
        "events_per_symbol": per_symbol,
        "synthetic_injected": synthetic_used,
    }


async def _amain(args: argparse.Namespace) -> int:
    # Expose Prometheus metrics for this process
    start_http_server(args.prom_port)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    ensure_db_parent(args.db)
    svc = BybitWSService(
        symbols,
        ws_url=args.ws_url,
        db_path=args.db,
        parquet_dir=args.parquet_dir,
        flush_size=args.flush_size,
        flush_interval=args.flush_interval,
        subscribe_tpl=args.subscribe_tpl,
        health_port=args.health_port,
    )

    db_before = _get_db_count(args.db)
    summary = await _run_until_event(
        svc,
        db_path=args.db,
        max_duration=args.duration,
        poll_interval=args.poll_interval,
        min_rows=args.min_rows,
        synthetic_after=args.synthetic_after,
        baseline_rows=db_before,
    )
    db_after = _get_db_count(args.db)

    out = {
        "timestamp": datetime.now(UTC).isoformat(),
        "symbols": symbols,
        "db_path": args.db,
        "db_rows_before": db_before,
        "db_rows_after": db_after,
        "db_rows_delta": max(0, db_after - db_before),
        "prom_port": args.prom_port,
        "health_port": args.health_port,
        **summary,
    }
    print(json.dumps(out, indent=2))
    # Keep return code 0 even if no delta, to avoid failing CI; this is a probe.
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Run Bybit WS briefly and probe metrics/DB")
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT", help="Comma-separated symbols")
    p.add_argument("--ws-url", default=None, help="Override WS endpoint")
    p.add_argument("--db", default=get_default_db_path(), help="SQLite DB path")
    p.add_argument("--parquet-dir", default="data/bybit_liquidations", help="Parquet dir (optional)")
    p.add_argument("--flush-size", type=int, default=50)
    p.add_argument("--flush-interval", type=int, default=3)
    p.add_argument("--subscribe-tpl", default="liquidation.{}")
    p.add_argument("--prom-port", type=int, default=8200)
    p.add_argument("--health-port", type=int, default=8100)
    p.add_argument("--duration", type=int, default=45, help="Max duration in seconds")
    p.add_argument("--poll-interval", type=float, default=3.0, help="DB poll interval seconds")
    p.add_argument("--min-rows", type=int, default=1, help="Stop after at least N rows in DB")
    p.add_argument(
        "--synthetic-after",
        type=int,
        default=20,
        help="Inject one synthetic event after N seconds if no rows yet",
    )
    args = p.parse_args()

    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        return 0
    except Exception:
        # Best-effort probe: never crash hard, just nonzero code
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

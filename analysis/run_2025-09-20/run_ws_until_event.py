import asyncio
import contextlib
import json
import os
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

async def run_ws_until_event(symbols=None, max_duration=180, min_events=1):
    symbols = symbols or ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
    with contextlib.suppress(Exception):
        start_http_server(8021)

    svc = BybitWSService(symbols, flush_interval=10, flush_size=100)

    # Observations accumulées
    start_time = time.time()

    async def monitor_events():
        # Poll metrics _metrics internal mapping every 2s
        while True:
            await asyncio.sleep(2)
            events_total = 0
            try:
                for metric in getattr(BYBIT_WS_EVENTS, "_metrics", {}).values():  # type: ignore[attr-defined]
                    events_total += int(getattr(metric, "_value", 0))
            except Exception:
                pass
            elapsed = time.time() - start_time
            if events_total >= min_events or elapsed >= max_duration:
                await svc.stop()
                break

    run_task = asyncio.create_task(svc.run())
    monitor_task = asyncio.create_task(monitor_events())

    await asyncio.gather(run_task, monitor_task)
    elapsed = time.time() - start_time

    # Collect per-symbol events
    per_symbol = {}
    try:
        for labels, metric in getattr(BYBIT_WS_EVENTS, "_metrics", {}).items():  # type: ignore[attr-defined]
            if isinstance(labels, tuple) and labels:
                symbol = labels[0]
                per_symbol[symbol] = int(getattr(metric, "_value", 0))
    except Exception:
        pass

    def _extract_val(counter_obj):
        val = getattr(counter_obj, "_value", 0)
        try:
            return int(val.get())  # type: ignore[attr-defined]
        except Exception:
            try:
                return int(val)
            except Exception:
                return 0

    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "connections_total": _extract_val(BYBIT_WS_CONNECTIONS),
        "errors_total": _extract_val(BYBIT_WS_ERRORS),
        "events_per_symbol": per_symbol,
        "min_events_target": min_events,
        "max_duration_seconds": max_duration,
        "symbols": symbols,
    }

    out_path = os.path.join(ARTIFACT_DIR, "ws_until_event_summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("WS until-event summary saved:", summary)

if __name__ == '__main__':
    asyncio.run(run_ws_until_event())

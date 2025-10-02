"""WebSocket session runner with optional offline injection for deterministic tests.

Deux modes:
1. live: ouvre une vraie connexion WS (BybitWSService) avec reconnexion forcée.
2. inject: lit un fichier JSONL d'évènements liquidation synthétiques et incrémente les métriques
   sans ouvrir de socket réseau (deterministic, rapide, no-flake).

La fonction renvoie aussi le summary (utile dans les tests) et l'écrit dans un artifact JSON.
"""

import asyncio
import contextlib
import enum
import json
import os
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from prometheus_client import start_http_server

from pipeline.collectors.bybit_ws import (
    BYBIT_WS_CONNECTIONS,
    BYBIT_WS_ERRORS,
    BYBIT_WS_EVENTS,
    BybitWSService,
)

ARTIFACT_DIR = "analysis/run_2025-09-20/artifacts"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

# Cache interne pour le mode injection (évite introspection fragile des métriques Prometheus)
_INJECT_EVENT_CACHE: dict[str, int] = {}

class Mode(enum.Enum):
    LIVE = "live"
    INJECT = "inject"

def _extract_counter_val(counter_obj) -> int:
    val = getattr(counter_obj, '_value', 0)
    try:
        return int(val.get())  # type: ignore[attr-defined]
    except Exception:
        try:
            return int(val)
        except Exception:
            return 0

def _collect_events_samples() -> dict[str, int]:
    events_samples: dict[str, int] = {}
    try:
        for labels, metric in getattr(BYBIT_WS_EVENTS, "_metrics", {}).items():  # type: ignore[attr-defined]
            if isinstance(labels, tuple) and labels:
                symbol = labels[0]
                count = int(getattr(metric, "_value", 0))
                events_samples[symbol] = count
    except Exception:
        pass
    return events_samples

async def _run_live(symbols: list[str], duration: int, force_close_after: int, prometheus_port: int) -> None:
    with contextlib.suppress(Exception):
        start_http_server(prometheus_port)
    svc = BybitWSService(symbols, flush_interval=5, flush_size=50)

    async def induce_close():
        await asyncio.sleep(force_close_after)
        if svc.ws:
            with contextlib.suppress(Exception):
                await svc.ws.close()

    async def stopper():
        await asyncio.sleep(duration)
        await svc.stop()

    await asyncio.gather(
        asyncio.create_task(svc.run()),
        asyncio.create_task(induce_close()),
        asyncio.create_task(stopper()),
        return_exceptions=True,
    )

def _iter_injection_events(path: str) -> Iterable[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj

async def _run_inject(path: str, symbols: list[str]) -> None:
    for ev in _iter_injection_events(path):
        sym = ev.get("symbol") or ev.get("symbolName") or ev.get("s")
        if not sym or sym not in symbols:
            continue
        BYBIT_WS_EVENTS.labels(symbol=sym).inc()
        _INJECT_EVENT_CACHE.setdefault(sym, 0)
        _INJECT_EVENT_CACHE[sym] += 1
        if _extract_counter_val(BYBIT_WS_CONNECTIONS) == 0:
            BYBIT_WS_CONNECTIONS.inc()

async def run_ws_session(
    mode: str = "live",
    symbols: list[str] | None = None,
    duration: int = 10,
    force_close_after: int = 4,
    prometheus_port: int = 8020,
    injection_file: str | None = None,
) -> dict[str, Any]:
    symbols = symbols or ["BTCUSDT", "ETHUSDT"]
    started = time.time()
    if mode == Mode.LIVE.value:
        await _run_live(symbols, duration, force_close_after, prometheus_port)
    elif mode == Mode.INJECT.value:
        if not injection_file or not os.path.exists(injection_file):
            raise FileNotFoundError(f"Injection file not found: {injection_file}")
        await _run_inject(injection_file, symbols)
    else:
        raise ValueError(f"Unknown mode: {mode}")
    elapsed = time.time() - started

    events_per_symbol = _collect_events_samples()
    # Fusion propre avec cache injection si présent
    if _INJECT_EVENT_CACHE:
        events_per_symbol.update(_INJECT_EVENT_CACHE)

    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "mode": mode,
        "symbols": symbols,
        "duration_seconds": round(elapsed, 3),
        "connections_total": _extract_counter_val(BYBIT_WS_CONNECTIONS),
        "errors_total": _extract_counter_val(BYBIT_WS_ERRORS),
        "events_per_symbol": events_per_symbol,
        "forced_close_after_seconds": force_close_after if mode == Mode.LIVE.value else None,
        "injection_file": injection_file,
    }

    out_path = os.path.join(ARTIFACT_DIR, f"ws_session_summary_{mode}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("WS session summary saved:", summary)
    return summary

if __name__ == "__main__":  # pragma: no cover - manual execution path
    asyncio.run(run_ws_session())

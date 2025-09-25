"""Génère un snapshot JSON unifié des collectors principaux.
Sortie: exports/runtime_snapshot.json

Politique:
- Chaque entrée: {"collector": str, "success": bool, "data": Any | None}
- Erreurs capturées avec champ error.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, TypedDict

from pipeline.collectors.defillama import DefillamaCollector
from pipeline.collectors.market import fetch_market
from pipeline.collectors.onchain import fetch_hashrate, fetch_sopr, fetch_txcount

OUTPUT = Path("exports/runtime_snapshot.json")

class Entry(TypedDict, total=False):
    collector: str
    success: bool
    data: Any | None
    error: str
    duration_ms: int

def _serialize(obj: Any) -> Any:
    if isinstance(obj, int | float | str | type(None)):
        return obj
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_serialize(x) for x in obj]
    return str(obj)

async def _run_async_collectors() -> dict[str, Any]:
    results: dict[str, Any] = {}
    # Async collectors: Defillama (wrap sync wrapper via thread?), onchain async functions
    # DefillamaCollector wrapper sync -> on peut l'exécuter dans thread pour ne pas bloquer boucle
    loop = asyncio.get_running_loop()
    defi = DefillamaCollector()
    start = time.perf_counter()
    try:
        tvl = await loop.run_in_executor(None, lambda: defi.fetch_tvl("ethereum"))
        results["defillama_tvl"] = {
            "collector": "defillama_tvl",
            "success": tvl is not None,
            "data": tvl,
            "duration_ms": int((time.perf_counter() - start) * 1000),
        }
    except Exception as e:  # pragma: no cover - robustesse
        results["defillama_tvl"] = {
            "collector": "defillama_tvl",
            "success": False,
            "error": str(e),
            "duration_ms": int((time.perf_counter() - start) * 1000),
        }

    # Onchain async
    for name, coro_factory in [
        ("onchain_txcount_btc", lambda: fetch_txcount("BTC")),
        ("onchain_hashrate_btc", lambda: fetch_hashrate("BTC")),
        ("onchain_sopr_btc", lambda: fetch_sopr("BTC")),
    ]:
        start = time.perf_counter()
        try:
            data = await coro_factory()
            results[name] = {
                "collector": name,
                "success": data is not None,
                "data": data,
                "duration_ms": int((time.perf_counter() - start) * 1000),
            }
        except Exception as e:  # pragma: no cover
            results[name] = {
                "collector": name,
                "success": False,
                "error": str(e),
                "duration_ms": int((time.perf_counter() - start) * 1000),
            }

    return results

def build_snapshot() -> list[Entry]:
    entries: list[Entry] = []
    # Market (sync)
    start = time.perf_counter()
    try:
        market = fetch_market("bitcoin")
        entries.append(
            {
                "collector": "market_bitcoin",
                "success": market is not None,
                "data": market,
                "duration_ms": int((time.perf_counter() - start) * 1000),
            }
        )
    except Exception as e:  # pragma: no cover
        entries.append(
            {
                "collector": "market_bitcoin",
                "success": False,
                "error": str(e),
                "duration_ms": int((time.perf_counter() - start) * 1000),
            }
        )

    # Async group
    async_results = asyncio.run(_run_async_collectors())
    entries.extend(async_results.values())
    return entries

def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    data = build_snapshot()
    serialized = _serialize(data)
    OUTPUT.write_text(json.dumps(serialized, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Snapshot écrit dans {OUTPUT}")

if __name__ == "__main__":  # pragma: no cover
    main()

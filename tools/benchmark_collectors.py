"""Benchmark des collectors.

Usage:
    python -m tools.benchmark_collectors \
        --collectors macro,market \
        --iterations 15 \
        --timeout 8 \
        --json-out benchmark.json \
        --table

Caractéristiques:
 - Exécution séquentielle (réduit bruit et corrélation) pour chaque collector.
 - Mesures: mean, p95, min, max, success_rate.
 - Timeout par appel via asyncio.wait_for.
 - Découverte simple par nom logique mappé à une fonction ou coroutine.

Limites:
 - Pas de parallélisme (peut être ajouté plus tard avec --concurrency, risque d'interférence réseau).
 - Pas de warmup distinct (first-call latence incluse).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger()

# Mapping collector name -> async callable
CollectorFn = Callable[[], Awaitable[Any]]


async def _lazy_import_macro():  # séparé pour éviter coût import global si inutile
    from pipeline.collectors.market import fetch_macro
    return await fetch_macro()


async def _lazy_import_market():
    # Exécuter sync dans thread pour ne pas bloquer event loop
    from functools import partial

    from pipeline.collectors.market import fetch_market  # sync wrapper décoré
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(fetch_market, "bitcoin"))


COLLECTOR_REGISTRY: dict[str, CollectorFn] = {
    "macro": _lazy_import_macro,
    "market": _lazy_import_market,
}


@dataclass
class BenchmarkResult:
    collector: str
    iterations: int
    success: int
    errors: int
    latencies: list[float]
    started_at: float
    ended_at: float
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.latencies:
            lat_sorted = sorted(self.latencies)
            idx_p95 = max(0, min(len(lat_sorted) - 1, math.ceil(0.95 * len(lat_sorted)) - 1))
            p95 = lat_sorted[idx_p95]
            mean_v = statistics.fmean(self.latencies)
            min_v = lat_sorted[0]
            max_v = lat_sorted[-1]
        else:
            p95 = mean_v = min_v = max_v = 0.0
        return {
            "collector": self.collector,
            "iterations": self.iterations,
            "success": self.success,
            "errors": self.errors,
            "success_rate": (self.success / self.iterations) if self.iterations else 0.0,
            "mean_latency": round(mean_v, 6),
            "p95_latency": round(p95, 6),
            "min_latency": round(min_v, 6),
            "max_latency": round(max_v, 6),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "notes": self.notes,
        }


async def run_benchmark(name: str, fn: CollectorFn, iterations: int, timeout: float) -> BenchmarkResult:
    latencies: list[float] = []
    success = 0
    errors = 0
    started = time.time()
    for i in range(iterations):
        t0 = time.perf_counter()
        try:
            await asyncio.wait_for(fn(), timeout=timeout)
            success += 1
        except Exception as e:  # noqa: BLE001
            errors += 1
            log.error("benchmark_iteration_error", collector=name, iteration=i, error=str(e))
        finally:
            latencies.append(time.perf_counter() - t0)
    ended = time.time()
    return BenchmarkResult(name, iterations, success, errors, latencies, started, ended)


async def main_async(args):
    selected = [c.strip() for c in args.collectors.split(",") if c.strip()]
    unknown = [c for c in selected if c not in COLLECTOR_REGISTRY]
    if unknown:
        raise SystemExit(f"Unknown collectors: {unknown}. Known: {list(COLLECTOR_REGISTRY)}")
    results: list[BenchmarkResult] = []
    for name in selected:
        log.info("benchmark_start_collector", collector=name, iterations=args.iterations)
        res = await run_benchmark(name, COLLECTOR_REGISTRY[name], args.iterations, args.timeout)
        results.append(res)
    data = [r.to_dict() for r in results]
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log.info("benchmark_json_written", path=args.json_out)
    if args.table:
        try:
            from tabulate import tabulate
            headers = [
                "collector", "iterations", "success", "errors", "success_rate",
                "mean_latency", "p95_latency", "min_latency", "max_latency"
            ]
            rows = [[d[h] for h in headers] for d in data]
            print(tabulate(rows, headers=headers))
        except Exception:  # pragma: no cover
            print(json.dumps(data, indent=2))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def parse_args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description="Benchmark collectors")
    p.add_argument("--collectors", default="macro,market", help="Liste séparée par virgules")
    p.add_argument("--iterations", type=int, default=5)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--json-out", dest="json_out")
    p.add_argument("--table", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    asyncio.run(main_async(args))


if __name__ == "__main__":  # pragma: no cover
    main()

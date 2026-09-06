"""Orchestrateur générique de fallbacks.

But: factoriser la logique récurrente (tiers, métriques, classification) afin de
réduire la duplication dans les collecteurs individuels.

API (version initiale simplifiée):

    async def run_fallback_chain(name, tiers: list[Callable[[], Awaitable[T]]]) -> T | None

Chaque tier est une coroutine sans argument qui retourne soit une valeur,
soit None et peut lever une exception. En cas d'exception on incrémente la
latence tier error et on passe au suivant. Sur succès on enregistre depth.

Instrumentation incluse:
  - fallback_tier_latency_seconds
  - fallback_tier_invocations_total
  - fallback_chain_depth
  - collector_error_types_total

Extension future: support sync callables, backoff, circuit breaker intégré.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from typing import Any, TypeVar

import structlog
from prometheus_client import Counter, Gauge, Histogram

from .errors import classify
from .metrics import (
    COLLECTOR_ERROR_TYPES_TOTAL,
    FALLBACK_CHAIN_DEPTH,
    FALLBACK_TIER_INVOCATIONS_TOTAL,
    FALLBACK_TIER_LATENCY_SECONDS,
)

log = structlog.get_logger()

T = TypeVar("T")


async def run_fallback_chain(collector: str, tiers: Sequence[Callable[[], Awaitable[T | None]]]) -> T | None:
    for idx, tier_coro in enumerate(tiers, start=1):
        start = time.perf_counter()
        status = "success"
        try:
            result = await tier_coro()
            elapsed = time.perf_counter() - start
            if result is not None:
                FALLBACK_TIER_LATENCY_SECONDS.labels(collector=collector, tier=str(idx), status=status).observe(elapsed)
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector=collector, tier=str(idx), status=status).inc()
                with suppress(Exception):  # pragma: no cover
                    FALLBACK_CHAIN_DEPTH.labels(collector=collector).set(idx)
                return result
            else:
                # Considéré comme échec logique (empty) -> status=error
                status = "error"
                FALLBACK_TIER_LATENCY_SECONDS.labels(collector=collector, tier=str(idx), status=status).observe(elapsed)
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector=collector, tier=str(idx), status=status).inc()
        except Exception as e:  # pragma: no cover - couvert partiellement par tests futurs
            status = "error"
            elapsed = time.perf_counter() - start
            FALLBACK_TIER_LATENCY_SECONDS.labels(collector=collector, tier=str(idx), status=status).observe(elapsed)
            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector=collector, tier=str(idx), status=status).inc()
            et = classify(e)
            with suppress(Exception):
                COLLECTOR_ERROR_TYPES_TOTAL.labels(collector=collector, error_type=et).inc()
            log.warning("fallback_tier_error", collector=collector, tier=idx, error=str(e), error_type=et)
    return None


"""Orchestrateur parallèle + fallback chain unifiés.

Contient:
  - run_fallback_chain : exécution séquentielle tiers
  - ParallelOrchestrator : exécution parallèle collectors (legacy tests)
"""

# Métriques orchestrateur parallèle (préservées pour tests)
_ORCH_TIMEOUTS = Counter("orchestrator_timeouts_total", "Total des exécutions terminées par timeout")
_ORCH_LAST_TS = Gauge("orchestrator_last_run_timestamp", "Timestamp (epoch) du dernier démarrage orchestrateur")

# Legacy exposed metrics expected by certain tests (unique instances)
orchestrator_executions = Counter("orchestrator_executions_total", "Total orchestrator executions", ["success"])
orchestrator_duration_seconds = Histogram("orchestrator_duration_seconds", "Orchestrator execution duration")
# Backwards compatibility alias used in tests
orchestrator_duration = orchestrator_duration_seconds


class ParallelOrchestrator:
    def __init__(self, collectors: list[Any] | None = None, *, strict_none_error: bool = False):
        self.collectors = collectors or []
        self.strict_none_error = strict_none_error
        self.execution_stats: dict[str, Any] = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "last_execution_time": 0.0,
            "last_execution_duration": 0.0,
        }

    def add_collector(self, collector) -> None:
        self.collectors.append(collector)

    def remove_collector(self, name: str) -> bool:  # nouveau helper pour tests dynamiques
        for i, c in enumerate(self.collectors):
            if getattr(c, "name", None) == name:
                del self.collectors[i]
                return True
        return False

    async def run_all_collectors(self, timeout: float | None = None) -> dict[str, Any]:
        if not self.collectors:
            return {"status": "skipped", "reason": "no_collectors", "results": {}}
        start = time.time()
        exec_id = f"exec_{int(start)}"
        self.execution_stats["total_executions"] += 1
        with suppress(Exception):  # pragma: no cover
            _ORCH_LAST_TS.set(start)
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[self._safe(c, exec_id) for c in self.collectors], return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            orchestrator_executions.labels(success="false").inc()
            _ORCH_TIMEOUTS.inc()
            return {"status": "timeout", "execution_id": exec_id, "timeout_seconds": timeout}
        summary = self._summarize(results)
        dur = time.time() - start
        summary["execution_time_seconds"] = round(dur, 2)
        self.execution_stats["last_execution_time"] = float(start)
        self.execution_stats["last_execution_duration"] = float(dur)
        if summary["successful_count"] > 0:
            self.execution_stats["successful_executions"] += 1
            orchestrator_executions.labels(success="true").inc()
        else:
            self.execution_stats["failed_executions"] += 1
            orchestrator_executions.labels(success="false").inc()
        with suppress(Exception):  # pragma: no cover
            orchestrator_duration_seconds.observe(dur)
            with suppress(Exception):  # pragma: no cover
                # Support alias éventuellement patché dans tests (orchestrator_duration)
                orchestrator_duration.observe(dur)  # type: ignore[attr-defined]
        return {"status": "completed", "execution_id": exec_id, **summary}

    async def _safe(self, collector, exec_id: str):
        start = time.time()
        try:
            res = await collector.collect()
            if res is None and self.strict_none_error:
                raise RuntimeError("collector_returned_none")
            # incrémente métrique legacy succès
            with suppress(Exception):  # pragma: no cover
                collector_success_total.labels(collector=collector.name).inc()
            return {
                "collector": collector.name,
                "status": "success",
                "execution_time": round(time.time() - start, 2),
                "result": res,
            }
        except Exception as e:  # pragma: no cover (couvert par tests partiels)
            with suppress(Exception):  # pragma: no cover
                collector_error_total.labels(collector=getattr(collector, "name", "unknown")).inc()
            return {
                "collector": collector.name,
                "status": "error",
                "execution_time": round(time.time() - start, 2),
                "error": str(e),
                "error_type": type(e).__name__,
            }

    def _summarize(self, results: list[Any]) -> dict[str, Any]:
        succ = [r for r in results if isinstance(r, dict) and r.get("status") == "success"]
        fail = [r for r in results if isinstance(r, dict) and r.get("status") == "error"]
        exec_times = [r.get("execution_time", 0) for r in succ + fail if isinstance(r, dict)]
        avg = round(sum(exec_times) / len(exec_times), 2) if exec_times else 0
        return {
            "total_count": len(results),
            "successful_count": len(succ),
            "failed_count": len(fail),
            "success_rate": round((len(succ) / len(results)) * 100, 1) if results else 0,
            "avg_execution_time_seconds": avg,
            "successful_results": succ,
            "failed_results": fail,
        }

    # --- Legacy helper methods preserved for tests ---
    def _analyze_results(
        self, results: list, execution_id: str
    ) -> dict[str, Any]:  # pragma: no cover (legacy tests may hit)
        return self._summarize(results)

    def _summarize_result(self, result: Any) -> dict[str, Any]:  # pragma: no cover
        if result is None:
            return {"type": "none"}
        if isinstance(result, dict):
            return {"type": "dict", "keys_count": len(result.keys()), "sample_keys": list(result.keys())[:3]}
        if isinstance(result, list):
            return {"type": "list", "length": len(result), "sample_items": str(result[:2]) if result else "empty"}
        if isinstance(result, str):
            return {"type": "string", "length": len(result), "preview": result[:50]}
        return {"type": type(result).__name__, "preview": str(result)[:50]}

    def get_orchestrator_stats(self) -> dict[str, Any]:  # pragma: no cover
        return {
            "collectors_count": len(self.collectors),
            "execution_stats": self.execution_stats.copy(),
            "collectors": [getattr(c, "name", "?") for c in self.collectors],
        }


async def run_collectors_parallel(collectors: list[Any], timeout: float | None = None) -> dict[str, Any]:
    orch = ParallelOrchestrator(collectors)
    return await orch.run_all_collectors(timeout=timeout)


__all__ = [
    "run_fallback_chain",
    "ParallelOrchestrator",
    "run_collectors_parallel",
    # Legacy metric objects for backwards compatibility tests expect these names
    "collector_success_total",
    "collector_error_total",
    "orchestrator_timeouts_total",
    "last_orchestrator_run_ts",
    "orchestrator_executions",
    "orchestrator_duration_seconds",
    "orchestrator_duration",
]

# Expose legacy metric names expected by tests
collector_success_total = Counter(
    "orchestrator_collector_success_total", "Total des succès par collector", ["collector"]
)
collector_error_total = Counter("orchestrator_collector_error_total", "Total des erreurs par collector", ["collector"])
orchestrator_timeouts_total = _ORCH_TIMEOUTS
last_orchestrator_run_ts = _ORCH_LAST_TS

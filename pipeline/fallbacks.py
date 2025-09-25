"""Orchestrateur générique de fallbacks.

Permet de décrire une chaîne d'étapes (tiers) avec instrumentation unifiée.
Chaque étape est une coroutine ou fonction sync retournant un résultat vérité.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import structlog

from pipeline.circuit_breaker import record_failure, record_success, should_skip
from pipeline.errors import classify
from pipeline.metrics import (
    COLLECTOR_ERROR_TYPES_TOTAL,
    FALLBACK_CHAIN_DEPTH,
    FALLBACK_INVOCATIONS_TOTAL,
    FALLBACK_TIER_INVOCATIONS_TOTAL,
    fallback_tier_timing,
)

log = structlog.get_logger(__name__)

StepFn = Callable[[], Any]  # peut retourner Awaitable

async def _maybe_await(res: Any) -> Any:
    if asyncio.iscoroutine(res) or isinstance(res, Awaitable):
        return await res  # type: ignore
    return res

async def execute_fallback_chain(
    collector: str,
    steps: Iterable[tuple[str, StepFn]],
    *,
    breaker_name: str | None = None,
) -> Any | None:
    """Exécute les steps séquentiellement jusqu'au premier succès.

    Instrumente :
      - latence par tier
      - compteur success/error par tier
      - profondeur chain_depth
      - classification d'erreurs
    """
    br_name = breaker_name or collector
    if should_skip(br_name):
        log.warning("collector_breaker_open", collector=collector, breaker=br_name)
        return None
    depth = 0
    for name, fn in steps:
        depth += 1
        with fallback_tier_timing(collector, depth):
            try:
                result = await _maybe_await(fn())
                if result:
                    from contextlib import suppress
                    with suppress(Exception):  # pragma: no cover
                        FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                            collector=collector,
                            tier=str(depth),
                            status="success",
                        ).inc()
                        FALLBACK_CHAIN_DEPTH.labels(collector=collector).set(depth)
                    record_success(br_name)
                    if depth > 1:
                        FALLBACK_INVOCATIONS_TOTAL.labels(collector=collector, status="success").inc()
                    log.info("collector_fallback_success", collector=collector, tier=depth, step=name)
                    return result
                else:
                    # Considéré comme erreur fonctionnelle
                    FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                        collector=collector,
                        tier=str(depth),
                        status="error",
                    ).inc()
            except Exception as e:  # capture erreur
                etype = classify(e)
                from contextlib import suppress
                with suppress(Exception):  # pragma: no cover
                    COLLECTOR_ERROR_TYPES_TOTAL.labels(
                        collector=collector,
                        error_type=etype,
                    ).inc()
                    FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                        collector=collector,
                        tier=str(depth),
                        status="error",
                    ).inc()
                    if depth > 1:
                        FALLBACK_INVOCATIONS_TOTAL.labels(
                            collector=collector,
                            status="error",
                        ).inc()
                log.error(
                    "collector_step_error",
                    collector=collector,
                    tier=depth,
                    step=name,
                    error=str(e),
                    error_type=etype,
                )
                record_failure(br_name)
                continue
    # Aucun succès
    record_failure(br_name)
    log.warning("collector_all_fallbacks_failed", collector=collector, depth=depth)
    return None

__all__ = ["execute_fallback_chain"]

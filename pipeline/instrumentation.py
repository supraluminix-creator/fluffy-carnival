"""Instrumentation décorateurs pour collectors.

Ajoute métriques:
 - collector_runs_total
 - collector_duration_seconds
 - collector_error_types_total
"""
from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Callable

from pipeline.metrics.collectors import (
    COLLECTOR_RUNS_TOTAL,
    COLLECTOR_DURATION_SECONDS,
    COLLECTOR_ERROR_TYPES_TOTAL,
)
from pipeline.errors import classify


def instrument_collector(name: str):
    def decorator(fn: Callable[..., Any]):
        is_coro = asyncio.iscoroutinefunction(fn)

        if is_coro:
            async def inner(*args, **kwargs):  # type: ignore
                start = time.perf_counter()
                status = "success"
                try:
                    result = await fn(*args, **kwargs)
                except Exception as e:  # noqa: BLE001
                    status = "error"
                    try:
                        COLLECTOR_ERROR_TYPES_TOTAL.labels(collector=name, error_type=classify(e)).inc()
                    except Exception:  # pragma: no cover
                        pass
                    try:
                        COLLECTOR_RUNS_TOTAL.labels(collector=name, status=status).inc()
                        COLLECTOR_DURATION_SECONDS.labels(collector=name, status=status).observe(time.perf_counter()-start)
                    except Exception:  # pragma: no cover
                        pass
                    raise
                else:
                    try:
                        COLLECTOR_RUNS_TOTAL.labels(collector=name, status=status).inc()
                        COLLECTOR_DURATION_SECONDS.labels(collector=name, status=status).observe(time.perf_counter()-start)
                    except Exception:  # pragma: no cover
                        pass
                    return result
            return functools.wraps(fn)(inner)
        else:
            def inner(*args, **kwargs):  # type: ignore
                start = time.perf_counter()
                status = "success"
                try:
                    result = fn(*args, **kwargs)
                except Exception as e:  # noqa: BLE001
                    status = "error"
                    try:
                        COLLECTOR_ERROR_TYPES_TOTAL.labels(collector=name, error_type=classify(e)).inc()
                    except Exception:  # pragma: no cover
                        pass
                    try:
                        COLLECTOR_RUNS_TOTAL.labels(collector=name, status=status).inc()
                        COLLECTOR_DURATION_SECONDS.labels(collector=name, status=status).observe(time.perf_counter()-start)
                    except Exception:  # pragma: no cover
                        pass
                    raise
                else:
                    try:
                        COLLECTOR_RUNS_TOTAL.labels(collector=name, status=status).inc()
                        COLLECTOR_DURATION_SECONDS.labels(collector=name, status=status).observe(time.perf_counter()-start)
                    except Exception:  # pragma: no cover
                        pass
                    return result
            return functools.wraps(fn)(inner)
    return decorator

__all__ = ["instrument_collector"]

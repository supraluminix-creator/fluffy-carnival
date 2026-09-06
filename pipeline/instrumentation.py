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
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from pipeline.errors import classify
from pipeline.metrics.collectors import (
    COLLECTOR_DURATION_SECONDS,
    COLLECTOR_ERROR_TYPES_TOTAL,
    COLLECTOR_RUNS_TOTAL,
)


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
                    with suppress(Exception):  # pragma: no cover - instrumentation best-effort
                        COLLECTOR_ERROR_TYPES_TOTAL.labels(collector=name, error_type=classify(e)).inc()
                    with suppress(Exception):  # pragma: no cover - instrumentation best-effort
                        COLLECTOR_RUNS_TOTAL.labels(collector=name, status=status).inc()
                        COLLECTOR_DURATION_SECONDS.labels(collector=name, status=status).observe(
                            time.perf_counter() - start
                        )
                    raise
                else:
                    with suppress(Exception):  # pragma: no cover - instrumentation best-effort
                        COLLECTOR_RUNS_TOTAL.labels(collector=name, status=status).inc()
                        COLLECTOR_DURATION_SECONDS.labels(collector=name, status=status).observe(
                            time.perf_counter() - start
                        )
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
                    with suppress(Exception):  # pragma: no cover - instrumentation best-effort
                        COLLECTOR_ERROR_TYPES_TOTAL.labels(collector=name, error_type=classify(e)).inc()
                    with suppress(Exception):  # pragma: no cover - instrumentation best-effort
                        COLLECTOR_RUNS_TOTAL.labels(collector=name, status=status).inc()
                        COLLECTOR_DURATION_SECONDS.labels(collector=name, status=status).observe(
                            time.perf_counter() - start
                        )
                    raise
                else:
                    with suppress(Exception):  # pragma: no cover - instrumentation best-effort
                        COLLECTOR_RUNS_TOTAL.labels(collector=name, status=status).inc()
                        COLLECTOR_DURATION_SECONDS.labels(collector=name, status=status).observe(
                            time.perf_counter() - start
                        )
                    return result

            return functools.wraps(fn)(inner)

    return decorator


__all__ = ["instrument_collector"]

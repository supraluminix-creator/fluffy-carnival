"""Module legacy conservé pour compat rétro mais redirigé.

Les anciennes métriques REQUEST_LATENCY / REQUEST_ERRORS / REQUEST_SUCCESS
étaient des primitives peu granulaires. Elles sont désormais couvertes par
``pipeline.metrics`` (collectors.*) fournissant:
 - COLLECTOR_DURATION_SECONDS (histogram)
 - COLLECTOR_RUNS_TOTAL (success/error)
 - COLLECTOR_ERROR_TYPES_TOTAL (typologie)

On expose des alias vers les nouveaux compteurs pour éviter rupture.
"""
from __future__ import annotations

import warnings
from contextlib import suppress

from prometheus_client import start_http_server  # pragma: no cover

from .metrics import (
    COLLECTOR_DURATION_SECONDS,
    COLLECTOR_RUNS_TOTAL,
)

warnings.warn(
    "pipeline.monitoring est déprécié et sera retiré dans une future version; utilisez pipeline.metrics",
    DeprecationWarning,
    stacklevel=2,
)

# ---------------------------------------------------------------------------
# Shims de compatibilité: l'ancienne API exposait des métriques avec un seul
# label «collector». Les nouvelles métriques ont des labels supplémentaires
# (status / error_type). On fournit donc de petits wrappers qui acceptent
# uniquement collector et injectent des valeurs par défaut pour les labels
# supplémentaires. L'objectif du test `test_metrics_labels` est simplement
# de vérifier l'absence d'exception lors de l'appel.
# ---------------------------------------------------------------------------

class _LegacyHistogramShim:
    def __init__(self, underlying):
        self._underlying = underlying

    class _Child:
        def __init__(self, underlying, collector: str):
            self._underlying = underlying
            self._collector = collector

        def observe(self, value: float):  # type: ignore[override]
            # On mappe sur status="success" par défaut
            self._underlying.labels(collector=self._collector, status="success").observe(value)

    def labels(self, *args, **kwargs):  # type: ignore[override]
        collector = kwargs.get("collector") if kwargs else (args[0] if args else None)
        if collector is None:
            raise ValueError("collector label is required")
        return self._Child(self._underlying, collector)


class _LegacyCounterShim:
    def __init__(self, underlying, fixed_labels: dict[str, str]):
        self._underlying = underlying
        self._fixed = fixed_labels

    class _Child:
        def __init__(self, underlying, fixed: dict[str, str], collector: str):
            self._underlying = underlying
            self._fixed = fixed
            self._collector = collector

        def inc(self, amount: float = 1.0):  # type: ignore[override]
            self._underlying.labels(collector=self._collector, **self._fixed).inc(amount)

    def labels(self, *args, **kwargs):  # type: ignore[override]
        collector = kwargs.get("collector") if kwargs else (args[0] if args else None)
        if collector is None:
            raise ValueError("collector label is required")
        return self._Child(self._underlying, self._fixed, collector)


# Expositions legacy attendues par tests
REQUEST_LATENCY = _LegacyHistogramShim(COLLECTOR_DURATION_SECONDS)
REQUEST_SUCCESS = _LegacyCounterShim(COLLECTOR_RUNS_TOTAL, {"status": "success"})
# Pour les erreurs on réutilise COLLECTOR_RUNS_TOTAL avec status=error
REQUEST_ERRORS = _LegacyCounterShim(COLLECTOR_RUNS_TOTAL, {"status": "error"})

def start_metrics_server(port: int = 8000):  # pragma: no cover - simple wrapper
    with suppress(OSError):
        start_http_server(port)

__all__ = [
    "REQUEST_LATENCY",
    "REQUEST_SUCCESS",
    "REQUEST_ERRORS",
    "start_metrics_server",
]
"""Prometheus metrics for TradingView swing reversal signals."""

from __future__ import annotations

from typing import cast

from prometheus_client import REGISTRY as GLOBAL_REGISTRY
from prometheus_client import Counter, Histogram, Gauge


def _counter(name: str, doc: str, labelnames: list[str]) -> Counter:
    try:
        return Counter(name, doc, labelnames)
    except ValueError:
        return cast(Counter, GLOBAL_REGISTRY._names_to_collectors.get(name))


def _histogram(name: str, doc: str, labelnames: list[str], **kwargs) -> Histogram:
    try:
        return Histogram(name, doc, labelnames, **kwargs)
    except ValueError:
        return cast(Histogram, GLOBAL_REGISTRY._names_to_collectors.get(name))


def _gauge(name: str, doc: str, labelnames: list[str]) -> Gauge:
    try:
        return Gauge(name, doc, labelnames)
    except ValueError:
        return cast(Gauge, GLOBAL_REGISTRY._names_to_collectors.get(name))


SIGNALS_RECEIVED_TOTAL = _counter(
    "signals_received",
    "Count of raw TradingView webhook payloads processed",
    ["status"],
)

SIGNALS_VALIDATED_TOTAL = _counter(
    "signals_validated",
    "Count of signals reviewed by the ML predictor",
    ["decision"],
)

ML_CONFIDENCE_HISTOGRAM = _histogram(
    "ml_confidence_histogram",
    "Histogram of ML confidence values for swing reversal signals",
    ["decision"],
    buckets=(0.1, 0.25, 0.5, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0),
)

# Correlation analysis metrics
CORRELATION_ANALYSIS_DURATION = _histogram(
    "correlation_analysis_duration_seconds",
    "Time spent computing correlation matrices",
    [],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)

CORRELATION_MATRIX_SIZE = _gauge(
    "correlation_matrix_size",
    "Number of assets in the current correlation matrix",
    [],
)

# Regime detection metrics
REGIME_DETECTION_DURATION = _histogram(
    "regime_detection_duration_seconds",
    "Time spent performing regime detection analysis",
    [],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)

VOLATILITY_CLUSTER_COUNT = _gauge(
    "volatility_cluster_count",
    "Number of volatility clusters detected",
    [],
)


__all__ = [
    "SIGNALS_RECEIVED_TOTAL",
    "SIGNALS_VALIDATED_TOTAL",
    "ML_CONFIDENCE_HISTOGRAM",
    "CORRELATION_ANALYSIS_DURATION",
    "CORRELATION_MATRIX_SIZE",
    "REGIME_DETECTION_DURATION",
    "VOLATILITY_CLUSTER_COUNT",
]

"""Métriques système (heartbeat, health endpoints, maintenance scheduler, HTTP retries)."""

from __future__ import annotations

from typing import cast

from prometheus_client import REGISTRY as GLOBAL_REGISTRY
from prometheus_client import Counter, Gauge, Histogram


def _counter(name: str, doc: str, labelnames: list[str]) -> Counter:
    try:
        return Counter(name, doc, labelnames)
    except ValueError:
        return cast(Counter, GLOBAL_REGISTRY._names_to_collectors.get(name))


def _gauge(name: str, doc: str, labelnames: list[str]) -> Gauge:
    try:
        return Gauge(name, doc, labelnames)
    except ValueError:
        return cast(Gauge, GLOBAL_REGISTRY._names_to_collectors.get(name))


def _histogram(name: str, doc: str, labelnames: list[str], **kwargs) -> Histogram:
    try:
        return Histogram(name, doc, labelnames, **kwargs)
    except ValueError:
        return cast(Histogram, GLOBAL_REGISTRY._names_to_collectors.get(name))


HEARTBEAT_TICKS_TOTAL = _counter(
    "heartbeat_ticks_total",
    "Nombre de ticks heartbeat",
    ["source"],
)
HEALTH_REQUESTS_TOTAL = _counter(
    "health_requests_total",
    "Requêtes sur endpoints health",
    ["endpoint", "status"],
)
MAINTENANCE_NEXT_RUN_TIMESTAMP = _gauge(
    "maintenance_next_run_timestamp", "Timestamp epoch planifié du prochain cycle maintenance (purge+vacuum)", []
)
MAINTENANCE_CYCLES_TOTAL = _counter(
    "maintenance_cycles_total",
    "Cycles maintenance exécutés (success/error)",
    ["status"],
)
HTTP_RETRIES_TOTAL = _counter(
    "http_retries_total",
    "Nombre total de tentatives HTTP supplémentaires (retries) effectuées",
    ["endpoint", "reason"],
)
HTTP_RETRY_ATTEMPT_LATENCY_SECONDS = _histogram(
    "http_retry_attempt_latency_seconds",
    "Latence par tentative HTTP (incluant retries)",
    ["endpoint", "attempt", "final_status"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

RETRY_BUDGET_REMAINING_SECONDS = _gauge(
    "http_retry_budget_remaining_seconds",
    "Budget cumulatif de sommeil retry restant pour l'endpoint (-1 = illimité)",
    ["endpoint"],
)
RETRY_BUDGET_EXHAUSTED_TOTAL = _counter(
    "http_retry_budget_exhausted_total",
    "Compteur d'épuisement du budget retry cumulatif",
    ["endpoint"],
)

__all__ = [
    "HEARTBEAT_TICKS_TOTAL",
    "HEALTH_REQUESTS_TOTAL",
    "MAINTENANCE_NEXT_RUN_TIMESTAMP",
    "MAINTENANCE_CYCLES_TOTAL",
    "HTTP_RETRIES_TOTAL",
    "HTTP_RETRY_ATTEMPT_LATENCY_SECONDS",
    "RETRY_BUDGET_REMAINING_SECONDS",
    "RETRY_BUDGET_EXHAUSTED_TOTAL",
]

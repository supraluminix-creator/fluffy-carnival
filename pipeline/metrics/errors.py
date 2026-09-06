"""Métriques de classification d'erreurs pour collectors."""

from __future__ import annotations

from typing import cast

from prometheus_client import REGISTRY as GLOBAL_REGISTRY
from prometheus_client import Counter


def _counter(name: str, doc: str, labelnames: list[str]) -> Counter:
    try:
        return Counter(name, doc, labelnames)
    except ValueError:
        # Déjà enregistré: récupérer l'instance existante depuis le registry
        return cast(Counter, GLOBAL_REGISTRY._names_to_collectors.get(name))


COLLECTOR_ERROR_TYPES_TOTAL = _counter(
    "collector_error_types_total",
    "Répartition des erreurs par type normalisé "
    "(schema,network,rate_limit,timeout,not_found,empty_data,upstream,unknown)",
    ["collector", "error_type"],
)

__all__ = [
    "COLLECTOR_ERROR_TYPES_TOTAL",
]

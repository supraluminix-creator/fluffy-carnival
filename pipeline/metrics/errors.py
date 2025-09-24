"""Métriques de classification d'erreurs pour collectors."""
from __future__ import annotations

from prometheus_client import Counter
from prometheus_client import REGISTRY as GLOBAL_REGISTRY


def _counter(name: str, doc: str, labelnames: list[str]):
	try:
		return Counter(name, doc, labelnames)
	except ValueError:
		return GLOBAL_REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]


COLLECTOR_ERROR_TYPES_TOTAL = _counter(
	"collector_error_types_total",
	"Répartition des erreurs par type normalisé (schema,network,rate_limit,timeout,not_found,empty_data,upstream,unknown)",
	["collector", "error_type"],
)

__all__ = [
	"COLLECTOR_ERROR_TYPES_TOTAL",
]

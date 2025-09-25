"""Métriques liées aux opérations d'export et au writer/flush."""
from __future__ import annotations

from typing import cast

from prometheus_client import REGISTRY as GLOBAL_REGISTRY
from prometheus_client import Counter, Gauge, Histogram


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


EXPORTS_TOTAL = _counter(
	"pipeline_exports_total",
	"Nombre d'exports CSV réalisés (success/error)",
	["status"],
)
EXPORT_ROWS_TOTAL = _counter(
	"pipeline_export_rows_total",
	"Nombre de lignes exportées", ["status"],
)

# Nouvelles métriques qualité des données export
EXPORT_ROW_REJECTIONS_TOTAL = _counter(
	"pipeline_export_row_rejections_total",
	"Nombre total de lignes rejetées lors de la validation (pydantic + contraintes internes)",
	["reason"],
)
EXPORT_VALUE_NEGATIVE_TOTAL = _counter(
	"pipeline_export_value_negative_total",
	"Nombre de lignes rejetées car 'value' négatif (contrainte valeur>=0)",
	["metric_name"],
)

FLUSH_OPERATIONS_TOTAL = _counter(
	"flush_operations_total",
	"Nombre total d'opérations de flush (success/noop)", ["writer", "status"],
)
BUFFER_LENGTH = _gauge(
	"writer_buffer_length",
	"Taille courante du buffer avant flush",
	["writer"],
)
LAST_FLUSH_TIMESTAMP = _gauge(
	"writer_last_flush_timestamp",
	"Timestamp epoch du dernier flush effectué",
	["writer"],
)
LAST_FLUSH_DURATION_SECONDS = _gauge(
    "last_flush_duration_seconds",
    "Durée (s) du dernier flush (toutes phases confondues)",
    ["writer"],
)
FLUSH_FAILURES_TOTAL = _counter(
	"flush_failures_total",
	"Nombre d'échecs de flush (exceptions durant écriture DB ou parquet)", ["writer", "phase"],
)
WRITER_FLUSH_LATENCY_SECONDS = _histogram(
	"writer_flush_latency_seconds",
	"Latence des opérations de flush (s)", ["writer", "status"], buckets=(0.01,0.05,0.1,0.25,0.5,1,2,5,10)
)

__all__ = [
	"EXPORTS_TOTAL",
	"EXPORT_ROWS_TOTAL",
	"EXPORT_ROW_REJECTIONS_TOTAL",
	"EXPORT_VALUE_NEGATIVE_TOTAL",
	"FLUSH_OPERATIONS_TOTAL",
	"BUFFER_LENGTH",
	"LAST_FLUSH_TIMESTAMP",
	"LAST_FLUSH_DURATION_SECONDS",
	"FLUSH_FAILURES_TOTAL",
	"WRITER_FLUSH_LATENCY_SECONDS",
]

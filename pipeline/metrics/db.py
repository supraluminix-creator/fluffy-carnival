"""Métriques base de données SQLite (taille, fragmentation, purge/vacuum)."""
from __future__ import annotations

from prometheus_client import Gauge, Counter
from prometheus_client import REGISTRY as GLOBAL_REGISTRY


def _gauge(name: str, doc: str, labelnames: list[str]):
	try:
		return Gauge(name, doc, labelnames)
	except ValueError:
		return GLOBAL_REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]


def _counter(name: str, doc: str, labelnames: list[str]):
	try:
		return Counter(name, doc, labelnames)
	except ValueError:
		return GLOBAL_REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]


DB_FILE_SIZE_BYTES = _gauge(
	"db_file_size_bytes", "Taille du fichier SQLite principal en octets", []
)
DB_LIQUIDATIONS_ROWS = _gauge(
	"db_liquidations_rows", "Nombre de lignes dans la table des liquidations agrégées", []
)
PURGE_OPERATIONS_TOTAL = _counter(
	"purge_operations_total", "Total des opérations de purge de données", ["table", "status", "mode"]
)
DB_VACUUM_DURATION_SECONDS = _gauge(
	"db_vacuum_duration_seconds", "Durée du dernier vacuum SQLite (s)", []
)
DB_PAGE_COUNT = _gauge(
	"db_page_count", "Nombre total de pages SQLite", []
)
DB_FREELIST_PAGES = _gauge(
	"db_freelist_pages", "Nombre de pages libres (freelist)", []
)
DB_FRAGMENTATION_RATIO = _gauge(
	"db_fragmentation_ratio", "Ratio freelist/total pages", []
)

__all__ = [
	"DB_FILE_SIZE_BYTES",
	"DB_LIQUIDATIONS_ROWS",
	"PURGE_OPERATIONS_TOTAL",
	"DB_VACUUM_DURATION_SECONDS",
	"DB_PAGE_COUNT",
	"DB_FREELIST_PAGES",
	"DB_FRAGMENTATION_RATIO",
]

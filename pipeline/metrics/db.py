"""Métriques base de données SQLite (taille, fragmentation, purge/vacuum)."""

from __future__ import annotations

from typing import cast

from prometheus_client import REGISTRY as GLOBAL_REGISTRY
from prometheus_client import Counter, Gauge


def _gauge(name: str, doc: str, labelnames: list[str]) -> Gauge:
    try:
        return Gauge(name, doc, labelnames)
    except ValueError:
        return cast(Gauge, GLOBAL_REGISTRY._names_to_collectors.get(name))


def _counter(name: str, doc: str, labelnames: list[str]) -> Counter:
    try:
        return Counter(name, doc, labelnames)
    except ValueError:
        return cast(Counter, GLOBAL_REGISTRY._names_to_collectors.get(name))


DB_FILE_SIZE_BYTES = _gauge("db_file_size_bytes", "Taille du fichier SQLite principal en octets", [])
DB_LIQUIDATIONS_ROWS = _gauge("db_liquidations_rows", "Nombre de lignes dans la table des liquidations agrégées", [])
PURGE_OPERATIONS_TOTAL = _counter(
    "purge_operations_total", "Total des opérations de purge de données", ["table", "status", "mode"]
)
DB_VACUUM_DURATION_SECONDS = _gauge("db_vacuum_duration_seconds", "Durée du dernier vacuum SQLite (s)", [])
DB_PAGE_COUNT = _gauge("db_page_count", "Nombre total de pages SQLite", [])
DB_FREELIST_PAGES = _gauge("db_freelist_pages", "Nombre de pages libres (freelist)", [])
DB_FRAGMENTATION_RATIO = _gauge("db_fragmentation_ratio", "Ratio freelist/total pages", [])

__all__ = [
    "DB_FILE_SIZE_BYTES",
    "DB_LIQUIDATIONS_ROWS",
    "PURGE_OPERATIONS_TOTAL",
    "DB_VACUUM_DURATION_SECONDS",
    "DB_PAGE_COUNT",
    "DB_FREELIST_PAGES",
    "DB_FRAGMENTATION_RATIO",
]

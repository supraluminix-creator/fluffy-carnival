"""Legacy stub.

Ancien fichier monolithique des métriques.
Conservé pour compat rétro : importe et ré-exporte tout depuis le package
segmenté `pipeline.metrics`.

NE PAS réintroduire ici de nouvelles définitions : ajouter dans un sous-module
du package (ex: pipeline/metrics/export.py, db.py, collectors.py, etc.).
"""

# Imports requis uniquement pour les helpers de compat ci‑dessous
import os

from contextlib import suppress
from prometheus_client import start_http_server

from .metrics.__init__ import *  # type: ignore  # noqa: F401,F403


def init_metrics_if_enabled() -> bool:
    if os.getenv("ENABLE_METRICS", "0") != "1":
        return False
    port = int(os.getenv("METRICS_PORT", "9300"))
    # Idempotent best-effort: si déjà lancé, ne relance pas
    with suppress(OSError):
        start_http_server(port)
    return True


def ensure_metrics() -> None:
    """Point d'entrée idempotent pour tests.

    Dans certains scénarios de tests on peut vouloir garantir que les symboles
    existent sans provoquer de double enregistrement. Ici tout est instancié
    au chargement du module; la fonction ne fait que servir de garde sémantique.
    """
    return None


__all__ = [  # noqa: F405 - ces symboles proviennent du import * ci-dessus
    "init_metrics_if_enabled",
    "ensure_metrics",
    "EXPORTS_TOTAL",
    "EXPORT_ROWS_TOTAL",
    "COLLECTOR_RUNS_TOTAL",
    "COLLECTOR_DURATION_SECONDS",
    "HEARTBEAT_TICKS_TOTAL",
    "HEALTH_REQUESTS_TOTAL",
    "FALLBACK_INVOCATIONS_TOTAL",
    "FALLBACK_TIER_INVOCATIONS_TOTAL",
    "FALLBACK_TIER_LATENCY_SECONDS",
    "FALLBACK_CHAIN_DEPTH",
    "COLLECTOR_ERROR_TYPES_TOTAL",
    "CB_LAST_OPEN_TIMESTAMP",
    "CB_RESETS_TOTAL",
    "FLUSH_OPERATIONS_TOTAL",
    "BUFFER_LENGTH",
    "LAST_FLUSH_TIMESTAMP",
    "DB_FILE_SIZE_BYTES",
    "DB_LIQUIDATIONS_ROWS",
    "PURGE_OPERATIONS_TOTAL",
    "DB_VACUUM_DURATION_SECONDS",
    "DB_PAGE_COUNT",
    "DB_FREELIST_PAGES",
    "DB_FRAGMENTATION_RATIO",
    "HTTP_RETRIES_TOTAL",
    "HTTP_RETRY_ATTEMPT_LATENCY_SECONDS",
    "CIRCUIT_BREAKER_OPEN_TOTAL",
    "CIRCUIT_BREAKER_SKIPS_TOTAL",
    "CIRCUIT_BREAKER_STATE",
    "CIRCUIT_BREAKER_OPEN_SECONDS",
    "HTTP_BREAKER_OPENS_TOTAL",
    "HTTP_BREAKER_SKIPS_TOTAL",
    "HTTP_BREAKER_STATE",
    "HTTP_BREAKER_OPEN_SECONDS",
    "FLUSH_FAILURES_TOTAL",
    "WRITER_FLUSH_LATENCY_SECONDS",
    "MAINTENANCE_NEXT_RUN_TIMESTAMP",
    "MAINTENANCE_CYCLES_TOTAL",
]

"""Namespace métriques segmenté.

Ce package regroupe et ré-exporte toutes les métriques Prometheus du pipeline
en sous-modules thématiques:

 - collectors: exécutions, latences, fallbacks
 - export: exports CSV, flush/writer
 - db: taille, fragmentation, purge/vacuum
 - system: heartbeat, health endpoints, maintenance, retries HTTP
 - breakers: breakers HTTP légers + circuit breakers génériques
 - errors: classification d'erreurs collectors

La séparation réduit le couplage et facilite l'évolution. Pour compatibilité,
les symboles restent accessibles via ``from pipeline import metrics`` comme avant.
"""
from __future__ import annotations

import os
from contextlib import suppress

from prometheus_client import start_http_server

from .breakers import *  # noqa: F401,F403
from .collectors import *  # noqa: F401,F403
from .db import *  # noqa: F401,F403
from .errors import *  # noqa: F401,F403
from .export import *  # noqa: F401,F403
from .system import *  # noqa: F401,F403


# Fonctions utilitaires héritées de l'ancien module
def init_metrics_if_enabled() -> bool:
	if os.getenv("ENABLE_METRICS", "0") != "1":
		return False
	port = int(os.getenv("METRICS_PORT", "9300"))
	with suppress(OSError):
		start_http_server(port)
	return True


def ensure_metrics() -> None:  # gardien sémantique utilisé dans certains tests
	return None

__all__ = [
	# functions
	"init_metrics_if_enabled",
	"ensure_metrics",
	# collectors
	*[s for s in (
		"COLLECTOR_RUNS_TOTAL","COLLECTOR_DURATION_SECONDS","FALLBACK_INVOCATIONS_TOTAL",
		"FALLBACK_TIER_INVOCATIONS_TOTAL","FALLBACK_TIER_LATENCY_SECONDS","FALLBACK_CHAIN_DEPTH",
		"collector_timing","fallback_tier_timing","FACADE_FORCED","FACADE_FORCED_LEAK","FACADE_DRY_RUN","set_facade_mode"
	)],
	# export
	*[s for s in (
		"EXPORTS_TOTAL","EXPORT_ROWS_TOTAL","FLUSH_OPERATIONS_TOTAL","BUFFER_LENGTH",
		"LAST_FLUSH_TIMESTAMP","FLUSH_FAILURES_TOTAL","WRITER_FLUSH_LATENCY_SECONDS",
		"EXPORT_ROW_REJECTIONS_TOTAL","EXPORT_VALUE_NEGATIVE_TOTAL"
	)],
	# db
	*[s for s in (
		"DB_FILE_SIZE_BYTES","DB_LIQUIDATIONS_ROWS","PURGE_OPERATIONS_TOTAL","DB_VACUUM_DURATION_SECONDS",
		"DB_PAGE_COUNT","DB_FREELIST_PAGES","DB_FRAGMENTATION_RATIO"
	)],
	# system
	*[s for s in (
		"HEARTBEAT_TICKS_TOTAL","HEALTH_REQUESTS_TOTAL","MAINTENANCE_NEXT_RUN_TIMESTAMP",
		"MAINTENANCE_CYCLES_TOTAL","HTTP_RETRIES_TOTAL","HTTP_RETRY_ATTEMPT_LATENCY_SECONDS"
	)],
	# breakers
	*[s for s in (
		"HTTP_BREAKER_OPENS_TOTAL","HTTP_BREAKER_SKIPS_TOTAL","HTTP_BREAKER_STATE","HTTP_BREAKER_OPEN_SECONDS",
		"CIRCUIT_BREAKER_OPEN_TOTAL","CIRCUIT_BREAKER_SKIPS_TOTAL","CIRCUIT_BREAKER_STATE","CIRCUIT_BREAKER_OPEN_SECONDS",
		"CB_LAST_OPEN_TIMESTAMP","CB_RESETS_TOTAL"
	)],
	# errors
	"COLLECTOR_ERROR_TYPES_TOTAL",
]

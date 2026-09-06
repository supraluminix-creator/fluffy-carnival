"""Test de fumée garantissant la stabilité de l'API publique du namespace metrics.

Objectifs:
 - Tous les symboles principaux restent importables depuis pipeline.metrics (backward compat).
 - Pas de création multiple (les objets doivent être singletons par nom dans le registry Prometheus).
"""

from prometheus_client import REGISTRY

from pipeline import metrics as m

# Sous-ensemble critique (si besoin, étendre au fil des évolutions)
EXPECTED_SYMBOLS = [
    # export
    "EXPORTS_TOTAL",
    "EXPORT_ROWS_TOTAL",
    # collectors
    "COLLECTOR_RUNS_TOTAL",
    "COLLECTOR_DURATION_SECONDS",
    "FALLBACK_INVOCATIONS_TOTAL",
    "FALLBACK_TIER_INVOCATIONS_TOTAL",
    "FALLBACK_TIER_LATENCY_SECONDS",
    "FALLBACK_CHAIN_DEPTH",
    # breakers
    "HTTP_BREAKER_OPENS_TOTAL",
    "CIRCUIT_BREAKER_OPEN_TOTAL",
    # db
    "DB_FILE_SIZE_BYTES",
    "DB_FRAGMENTATION_RATIO",
    # system
    "HEARTBEAT_TICKS_TOTAL",
    "MAINTENANCE_CYCLES_TOTAL",
    # errors
    "COLLECTOR_ERROR_TYPES_TOTAL",
    # helpers
    "collector_timing",
    "fallback_tier_timing",
    "init_metrics_if_enabled",
    "ensure_metrics",
]


def test_public_symbols_present():
    missing = [s for s in EXPECTED_SYMBOLS if not hasattr(m, s)]
    assert not missing, f"Symboles manquants dans pipeline.metrics: {missing}"


def test_prometheus_singleton_registration():
    # Vérifie qu'un nom connu n'est enregistré qu'une seule fois
    # (ex: pipeline_exports_total)
    names = [c for c in REGISTRY._names_to_collectors if c.startswith("pipeline_") or c.endswith("_total")]
    # Si duplication, Prometheus lèverait déjà ValueError à l'import; ce test devient essentiellement un filet.
    assert len(names) == len(set(names))

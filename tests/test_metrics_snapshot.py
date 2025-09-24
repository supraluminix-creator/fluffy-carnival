import importlib
from prometheus_client import REGISTRY

# Modules qui enregistrent les métriques personnalisées
MODULES = [
    'pipeline.metrics.collectors',
    'pipeline.metrics.export',
    'pipeline.metrics.db',
    'pipeline.metrics.system',
    'pipeline.metrics.breakers',
    'pipeline.llm.client',
    'pipeline.collectors.derivatives',  # dérivés
    'pipeline.collectors.bybit_liquidations',
    'pipeline.collectors.market',
    'pipeline.collectors.defillama',
    'pipeline.collectors.bybit_ws',
    'pipeline.collectors.onchain',
    'pipeline.collectors.sentiment',
    'pipeline.collectors.txcount',
    'pipeline.collectors.sopr',
    # Modules ajoutés pour enregistrer les familles manquantes
    'pipeline.collectors.bybit_OI',          # bybit_oi_* (latency/success/errors)
    'pipeline.collectors.base_collector',    # collector_* (base class definitions)
    'scheduler.runner',                      # crypto_* (readiness & task metrics)
]

EXPECTED = {
    # circuit breaker (HTTP + générique)
    'circuit_breaker_last_open_timestamp',
    'circuit_breaker_open',
    'circuit_breaker_open_seconds',
    'circuit_breaker_resets',
    'circuit_breaker_skips',
    'circuit_breaker_state',
    # collector instrumentation
    'collector_duration_seconds',
    'collector_error_types',
    'collector_runs',
    # db metrics
    'db_file_size_bytes',
    'db_fragmentation_ratio',
    'db_freelist_pages',
    'db_liquidations_rows',
    'db_page_count',
    'db_vacuum_duration_seconds',
    # derivatives legacy metrics
    'derivatives_breaker_skips',
    'derivatives_cache_hit',
    'derivatives_cache_miss',
    'derivatives_errors',
    'derivatives_latency_seconds',
    'derivatives_success',
    # fallback metrics
    'fallback_chain_depth',
    'fallback_invocations',
    'fallback_tier_invocations',
    'fallback_tier_latency_seconds',
    # export & writer
    'flush_failures',
    'flush_operations',
    'last_flush_duration_seconds',
    'writer_buffer_length',
    'writer_flush_latency_seconds',
    'writer_last_flush_timestamp',
    # health / maintenance / purge
    'health_requests',
    'heartbeat_ticks',
    'maintenance_cycles',
    'maintenance_next_run_timestamp',
    'purge_operations',
    # exporter pipeline
    'pipeline_export_row_rejections',
    'pipeline_export_rows',
    'pipeline_export_value_negative',
    'pipeline_exports',
    # http retry/breaker
    'http_breaker_open_seconds',
    'http_breaker_opens',
    'http_breaker_skips',
    'http_breaker_state',
    'http_retries',
    'http_retry_attempt_latency_seconds',
    'http_retry_budget_remaining_seconds',
    'http_retry_budget_exhausted',
    # --- Newly frozen families (post instrumentation expansion) ---
    'market_success', 'market_errors', 'market_cache_hit', 'market_cache_miss', 'market_breaker_skip', 'market_latency_seconds',
    'macro_success', 'macro_errors', 'macro_breaker_skip', 'macro_latency_seconds',
    'defillama_success', 'defillama_errors', 'defillama_cache_hit', 'defillama_cache_miss', 'defillama_breaker_skips', 'defillama_latency_seconds',
    'bybit_ws_connections', 'bybit_ws_events', 'bybit_ws_errors', 'bybit_ws_latency_seconds', 'bybit_ws_parse_errors',
    'bybit_oi_success', 'bybit_oi_errors', 'bybit_oi_latency_seconds',
    'orchestrator_executions', 'orchestrator_duration_seconds', 'orchestrator_last_run_timestamp', 'orchestrator_collector_success', 'orchestrator_collector_error', 'orchestrator_timeouts',
    'collector_success', 'collector_errors', 'collector_latency_seconds', 'collector_last_success_timestamp',
    'onchain_success', 'onchain_errors', 'onchain_latency_seconds',
    'sentiment_success', 'sentiment_errors', 'sentiment_latency_seconds',
    'txcount_success', 'txcount_errors', 'txcount_latency_seconds',
    'sopr_fetch_success', 'sopr_fetch_errors', 'sopr_fetch_latency_seconds',
    'crypto_ready', 'crypto_ready_timestamp', 'crypto_build_info',
    'crypto_task_start', 'crypto_task_ok', 'crypto_task_error', 'crypto_task_error_rate', 'crypto_task_duration_seconds',
    'legacy_http_usage',
    # Nouvelle gauge indiquant l'état forced de la façade HTTP
    'facade_forced',
    'facade_forced_leak',
    'facade_dry_run',
    # LLM instrumentation (quota/fallback client)
    'llm_requests',
    'llm_failures',
    'llm_fallbacks',
}

IGNORED_PREFIXES = ('python_', 'process_', 'prometheus_')

def _collect_names():
    for m in MODULES:
        importlib.import_module(m)
    names = {fam.name for fam in REGISTRY.collect() if not fam.name.startswith(IGNORED_PREFIXES)}
    return names


def test_metric_names_snapshot():
    names = _collect_names()
    missing = sorted(EXPECTED - names)
    unexpected = sorted(names - EXPECTED)
    # Autoriser ajout contrôlé: on force le dev à mettre à jour EXPECTED explicitement
    assert not missing, f"Metrics disparues: {missing}"
    assert not unexpected, f"Nouvelles metrics non déclarées dans snapshot: {unexpected}"

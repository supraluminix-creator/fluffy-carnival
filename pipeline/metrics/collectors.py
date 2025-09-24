"""Métriques liées aux collectors & fallbacks.

Contient les métriques d'exécution / latence des collecteurs ainsi que la chaîne
de fallbacks (invocations par tier, profondeur atteinte, latence).

Expose aussi des context managers utilitaires pour instrumenter facilement
les timings (``collector_timing`` et ``fallback_tier_timing``).
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import Counter, Histogram, Gauge
from prometheus_client import REGISTRY as GLOBAL_REGISTRY


def _counter(name: str, doc: str, labelnames: list[str]):  # idempotent helper
	try:
		return Counter(name, doc, labelnames)
	except ValueError:  # déjà défini
		return GLOBAL_REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]


def _histogram(name: str, doc: str, labelnames: list[str], **kwargs):
	try:
		return Histogram(name, doc, labelnames, **kwargs)
	except ValueError:
		return GLOBAL_REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]


def _gauge(name: str, doc: str, labelnames: list[str]):
	try:
		return Gauge(name, doc, labelnames)
	except ValueError:
		return GLOBAL_REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]


COLLECTOR_RUNS_TOTAL = _counter(
	"collector_runs_total",
	"Exécutions d'un collecteur (success/error)", ["collector", "status"],
)
COLLECTOR_ERROR_TYPES_TOTAL = _counter(
    "collector_error_types_total",
    "Occurrences d'erreurs catégorisées par collector (classification pipeline.errors.classify)",
    ["collector", "error_type"],
)
COLLECTOR_DURATION_SECONDS = _histogram(
	"collector_duration_seconds",
	"Durée d'exécution des collecteurs",
	["collector", "status"],
	buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
FALLBACK_INVOCATIONS_TOTAL = _counter(
	"fallback_invocations_total",
	"Nombre d'invocations de fallback (success/error)", ["collector", "status"],
)
FALLBACK_TIER_INVOCATIONS_TOTAL = _counter(
	"fallback_tier_invocations_total",
	"Invocations par niveau de fallback (tier=1 primaire, 2 premier fallback, etc.)",
	["collector", "tier", "status"],
)
FALLBACK_TIER_LATENCY_SECONDS = _histogram(
	"fallback_tier_latency_seconds",
	"Latence par niveau de fallback (primaire/tier n)",
	["collector", "tier", "status"],
	buckets=(0.05,0.1,0.25,0.5,1,2,5,10,30)
)
FALLBACK_CHAIN_DEPTH = _gauge(
	"fallback_chain_depth",
	"Profondeur atteinte dans la chaîne de fallbacks (1=primaire,2=1er fallback, etc.)",
	["collector"],
)

# Indicateur booléen (0/1) : le collector est-il exécuté en mode façade forcé ?
FACADE_FORCED = _gauge(
	"facade_forced",
	"Indique si la façade HTTP est forcée (FORCE_HTTP_FACADE=1) pour ce collector au moment de l'appel",
	["collector"],
)

# Indicateur dry-run (0/1) : DRY_RUN_FACADE activé au moment de l'appel
FACADE_DRY_RUN = _gauge(
	"facade_dry_run",
	"Indique si la façade HTTP est en mode DRY-RUN (DRY_RUN_FACADE=1) pour ce collector (évaluation sans couper legacy)",
	["collector"],
)

# Gauge fuite: vaut 1 si un usage legacy HTTP est détecté alors que le mode forced est actif
FACADE_FORCED_LEAK = _gauge(
	"facade_forced_leak",
	"Fuite: utilisation d'un chemin HTTP legacy alors que FORCE_HTTP_FACADE=1 (0=OK,1=LEAK)",
	["collector"],
)

# Pré-initialise les collectors connus à 0 pour stabiliser dashboards / snapshots
for _c in ("market","defillama","binance_spot","binance_oi","binance_funding","deriv_funding","deriv_lsr","sentiment","onchain_txcount","onchain_hashrate","onchain_sopr"):
	try:  # pragma: no cover - idempotent
		FACADE_FORCED.labels(collector=_c).set(0)  # type: ignore[attr-defined]
	except Exception:  # pragma: no cover
		pass
	try:
		FACADE_DRY_RUN.labels(collector=_c).set(0)  # type: ignore[attr-defined]
	except Exception:  # pragma: no cover
		pass
	try:  # initialise aussi leak gauge
		FACADE_FORCED_LEAK.labels(collector=_c).set(0)  # type: ignore[attr-defined]
	except Exception:  # pragma: no cover
		pass


def mark_legacy_http(collector: str):
	"""Incrémente le compteur legacy et déclenche la gauge fuite si mode forced.

	Utilisé par les collectors pour centraliser la logique prodsafe: si un chemin
	legacy est atteint alors que FORCE_HTTP_FACADE=1, on arme `facade_forced_leak=1`.
	"""
	try:
		from prometheus_client import REGISTRY as _R
		ctr = _R._names_to_collectors.get('legacy_http_usage_total')  # type: ignore[attr-defined]
		if ctr is not None:  # Counter
			ctr.labels(collector=collector).inc()  # type: ignore[call-arg]
		# Détection de fuite uniquement ici (et plus dans set_facade_mode)
		try:  # import local pour éviter cycles
			from pipeline.flags import is_forced_facade  # type: ignore
			if is_forced_facade():  # si on observe un chemin legacy alors que forced => fuite
				FACADE_FORCED_LEAK.labels(collector=collector).set(1)  # type: ignore[attr-defined]
		except Exception:  # pragma: no cover
			pass
	except Exception:  # pragma: no cover
		pass


def set_facade_mode(collector: str, forced: bool, dry_run: bool):
	"""Positionne les gauges facade_forced et facade_dry_run pour un collector.

	Idempotent: toujours setter (0 ou 1) afin de figer les séries dans les snapshots.
	"""
	try:
		FACADE_FORCED.labels(collector=collector).set(1 if forced else 0)  # type: ignore[attr-defined]
	except Exception:  # pragma: no cover
		pass
	try:
		FACADE_DRY_RUN.labels(collector=collector).set(1 if dry_run else 0)  # type: ignore[attr-defined]
	except Exception:  # pragma: no cover
		pass
	# Reset proactif de la gauge leak en mode forced (elle ne passe à 1 que si un chemin legacy est réellement emprunté)
	if forced:
		try:
			FACADE_FORCED_LEAK.labels(collector=collector).set(0)  # type: ignore[attr-defined]
		except Exception:  # pragma: no cover
			pass


@contextmanager
def collector_timing(name: str) -> Iterator[None]:
	start = time.perf_counter()
	status = "success"
	try:
		yield
	except Exception:
		status = "error"
		COLLECTOR_RUNS_TOTAL.labels(collector=name, status=status).inc()
		COLLECTOR_DURATION_SECONDS.labels(collector=name, status=status).observe(time.perf_counter() - start)
		raise
	else:
		COLLECTOR_RUNS_TOTAL.labels(collector=name, status=status).inc()
		COLLECTOR_DURATION_SECONDS.labels(collector=name, status=status).observe(time.perf_counter() - start)


@contextmanager
def fallback_tier_timing(collector: str, tier: int):
	"""Chronométrer un appel (primaire ou fallback tier N) avec statut success/error."""
	start = time.perf_counter()
	status = "success"
	try:
		yield
	except Exception:
		status = "error"
		FALLBACK_TIER_LATENCY_SECONDS.labels(collector=collector, tier=str(tier), status=status).observe(time.perf_counter()-start)
		raise
	else:
		FALLBACK_TIER_LATENCY_SECONDS.labels(collector=collector, tier=str(tier), status=status).observe(time.perf_counter()-start)


__all__ = [
	"COLLECTOR_RUNS_TOTAL",
	"COLLECTOR_DURATION_SECONDS",
	"COLLECTOR_ERROR_TYPES_TOTAL",
	"FALLBACK_INVOCATIONS_TOTAL",
	"FALLBACK_TIER_INVOCATIONS_TOTAL",
	"FALLBACK_TIER_LATENCY_SECONDS",
	"FALLBACK_CHAIN_DEPTH",
	"FACADE_FORCED",
	"FACADE_FORCED_LEAK",
	"FACADE_DRY_RUN",
	"set_facade_mode",
	"collector_timing",
	"fallback_tier_timing",
]

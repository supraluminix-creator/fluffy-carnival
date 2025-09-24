"""Métriques des breakers (HTTP léger 429 + circuit breakers génériques)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge
from prometheus_client import REGISTRY as GLOBAL_REGISTRY


def _counter(name: str, doc: str, labelnames: list[str]):
	try:
		return Counter(name, doc, labelnames)
	except ValueError:
		return GLOBAL_REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]


def _gauge(name: str, doc: str, labelnames: list[str]):
	try:
		return Gauge(name, doc, labelnames)
	except ValueError:
		return GLOBAL_REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]


HTTP_BREAKER_OPENS_TOTAL = _counter(
	"http_breaker_opens_total",
	"Ouvertures du breaker léger 429 (wrappers HTTP)",
	["endpoint"],
)
HTTP_BREAKER_SKIPS_TOTAL = _counter(
	"http_breaker_skips_total",
	"Requêtes court-circuitées car breaker léger 429 ouvert",
	["endpoint"],
)
HTTP_BREAKER_STATE = _gauge(
	"http_breaker_state",
	"État du breaker léger 429 (1=open,0=closed)",
	["endpoint"],
)
HTTP_BREAKER_OPEN_SECONDS = _gauge(
	"http_breaker_open_seconds",
	"Âge (secondes) depuis ouverture du breaker léger (0 si fermé)",
	["endpoint"],
)

CIRCUIT_BREAKER_OPEN_TOTAL = _counter(
	"circuit_breaker_open_total",
	"Nombre total d'ouvertures de circuit breaker",
	["breaker"],
)
CIRCUIT_BREAKER_SKIPS_TOTAL = _counter(
	"circuit_breaker_skips_total",
	"Nombre de skips dus à un circuit breaker ouvert",
	["breaker"],
)
CIRCUIT_BREAKER_STATE = _gauge(
	"circuit_breaker_state",
	"État courant du circuit breaker (1=open,0=closed)",
	["breaker"],
)
CIRCUIT_BREAKER_OPEN_SECONDS = _gauge(
	"circuit_breaker_open_seconds",
	"Durée (s) depuis ouverture pour chaque breaker ouvert (0 si fermé)",
	["breaker"],
)
CB_LAST_OPEN_TIMESTAMP = _gauge(
	"circuit_breaker_last_open_timestamp",
	"Timestamp epoch de la dernière ouverture du breaker",
	["breaker"],
)
CB_RESETS_TOTAL = _counter(
	"circuit_breaker_resets_total",
	"Nombre de réinitialisations (passage open->closed)",
	["breaker"],
)

__all__ = [
	"HTTP_BREAKER_OPENS_TOTAL",
	"HTTP_BREAKER_SKIPS_TOTAL",
	"HTTP_BREAKER_STATE",
	"HTTP_BREAKER_OPEN_SECONDS",
	"CIRCUIT_BREAKER_OPEN_TOTAL",
	"CIRCUIT_BREAKER_SKIPS_TOTAL",
	"CIRCUIT_BREAKER_STATE",
	"CIRCUIT_BREAKER_OPEN_SECONDS",
	"CB_LAST_OPEN_TIMESTAMP",
	"CB_RESETS_TOTAL",
]

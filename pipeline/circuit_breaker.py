from __future__ import annotations

"""Circuit breaker léger en mémoire.

Usage:
    if should_skip("defillama"): return None
    try: ...; record_success("defillama")
    except: record_failure("defillama")

Seuil: 3 échecs consécutifs -> ouvert 30s.
"""

from dataclasses import dataclass
from time import time
from typing import Dict
try:  # import défensif (tests unit peuvent isoler)
    from pipeline.metrics import (
        CIRCUIT_BREAKER_OPEN_TOTAL,
        CIRCUIT_BREAKER_SKIPS_TOTAL,
        CIRCUIT_BREAKER_STATE,
        CIRCUIT_BREAKER_OPEN_SECONDS,
        CB_LAST_OPEN_TIMESTAMP,
        CB_RESETS_TOTAL,
        HTTP_RETRIES_TOTAL,  # non utilisé ici mais maintien compat import multi
    )
except Exception:  # pragma: no cover - fallback si metrics non initialisées
    CIRCUIT_BREAKER_OPEN_TOTAL = CIRCUIT_BREAKER_SKIPS_TOTAL = None  # type: ignore
    CIRCUIT_BREAKER_STATE = CIRCUIT_BREAKER_OPEN_SECONDS = None  # type: ignore
    CB_LAST_OPEN_TIMESTAMP = CB_RESETS_TOTAL = None  # type: ignore


@dataclass
class _State:
    fail_count: int = 0
    opened_at: float | None = None  # timestamp d'ouverture si open
    threshold: int = 3
    cooldown: int = 30  # durée minimale d'ouverture avant tentative de réutilisation
    last_checked: float | None = None  # pour mise à jour périodique métriques
    half_open: bool = False  # True lorsqu'on autorise une tentative probe après cooldown
    half_open_attempted: bool = False  # Empêche multiples probes simultanées

    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time() - self.opened_at >= self.cooldown:
            # Cooldown écoulé -> reset
            self.fail_count = 0
            self.opened_at = None
            return False
        return True


_STATES: Dict[str, _State] = {}


def _get(name: str) -> _State:
    st = _STATES.get(name)
    if st is None:
        st = _State()
        _STATES[name] = st
    return st


def _update_open_metrics(name: str, st: _State) -> None:
    """Met à jour les métriques d'état ouvert (durée)."""
    if CIRCUIT_BREAKER_OPEN_SECONDS is not None and st.opened_at is not None:  # type: ignore[truthy-bool]
        try:
            CIRCUIT_BREAKER_OPEN_SECONDS.labels(breaker=name).set(time() - st.opened_at)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass


def should_skip(name: str) -> bool:
    st = _get(name)
    # Gestion half-open: si cooldown écoulé et breaker toujours marqué open -> passage half-open
    if st.opened_at is not None and not st.half_open and (time() - st.opened_at) >= st.cooldown:
        st.half_open = True
        st.fail_count = st.threshold  # conserve fail_count pour info
        # état 2 = half-open pour gauge
        if CIRCUIT_BREAKER_STATE is not None:  # type: ignore[truthy-bool]
            try:
                CIRCUIT_BREAKER_STATE.labels(breaker=name).set(2)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
    if st.half_open:
        # Autoriser exactement une tentative (probe)
        if st.half_open_attempted:
            if CIRCUIT_BREAKER_SKIPS_TOTAL is not None:  # type: ignore[truthy-bool]
                try:
                    CIRCUIT_BREAKER_SKIPS_TOTAL.labels(breaker=name).inc()  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover
                    pass
            return True
        st.half_open_attempted = True
        return False
    if st.is_open():
        # métriques skip
        if CIRCUIT_BREAKER_SKIPS_TOTAL is not None:  # type: ignore[truthy-bool]
            try:
                CIRCUIT_BREAKER_SKIPS_TOTAL.labels(breaker=name).inc()  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
        _update_open_metrics(name, st)
        return True
    else:
        # breaker fermé -> gauge état et durée=0
        if CIRCUIT_BREAKER_STATE is not None:  # type: ignore[truthy-bool]
            try:
                CIRCUIT_BREAKER_STATE.labels(breaker=name).set(0)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
        if CIRCUIT_BREAKER_OPEN_SECONDS is not None:  # type: ignore[truthy-bool]
            try:
                CIRCUIT_BREAKER_OPEN_SECONDS.labels(breaker=name).set(0)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
        return False


def record_failure(name: str) -> None:
    st = _get(name)
    st.fail_count += 1
    # Si half-open probe échoue -> ré-ouverture complète
    if st.half_open:
        st.opened_at = time()
        st.half_open = False
        st.half_open_attempted = False
        if CIRCUIT_BREAKER_STATE is not None:  # type: ignore[truthy-bool]
            try:
                CIRCUIT_BREAKER_STATE.labels(breaker=name).set(1)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
        return
    if st.fail_count >= st.threshold and st.opened_at is None:
        st.opened_at = time()
        st.last_checked = st.opened_at
        # ouverture breaker
        if CIRCUIT_BREAKER_OPEN_TOTAL is not None:  # type: ignore[truthy-bool]
            try:
                CIRCUIT_BREAKER_OPEN_TOTAL.labels(breaker=name).inc()  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
        if CIRCUIT_BREAKER_STATE is not None:  # type: ignore[truthy-bool]
            try:
                CIRCUIT_BREAKER_STATE.labels(breaker=name).set(1)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
        if CB_LAST_OPEN_TIMESTAMP is not None:  # type: ignore[truthy-bool]
            try:
                CB_LAST_OPEN_TIMESTAMP.labels(breaker=name).set(st.opened_at or 0)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
        _update_open_metrics(name, st)


def record_success(name: str) -> None:
    st = _get(name)
    # Si était ouvert on considère un reset complet pour métrique de reset.
    was_open = st.opened_at is not None or st.half_open
    st.fail_count = 0
    st.opened_at = None
    st.last_checked = time()
    st.half_open = False
    st.half_open_attempted = False
    # fermeture -> state=0, durée=0
    if CIRCUIT_BREAKER_STATE is not None:  # type: ignore[truthy-bool]
        try:
            CIRCUIT_BREAKER_STATE.labels(breaker=name).set(0)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass
    if CIRCUIT_BREAKER_OPEN_SECONDS is not None:  # type: ignore[truthy-bool]
        try:
            CIRCUIT_BREAKER_OPEN_SECONDS.labels(breaker=name).set(0)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass
    if was_open and CB_RESETS_TOTAL is not None:  # type: ignore[truthy-bool]
        try:
            CB_RESETS_TOTAL.labels(breaker=name).inc()  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass


def reset(name: str | None = None) -> None:  # pragma: no cover - utilitaire debug
    if name is None:
        _STATES.clear()
    else:
        _STATES.pop(name, None)


def breaker_status(name: str) -> dict[str, float | int | None]:
    """Expose un snapshot de l'état interne (debug / tests)."""
    st = _get(name)
    return {
        "fail_count": st.fail_count,
        "opened_at": st.opened_at,
        "threshold": st.threshold,
        "cooldown": st.cooldown,
        "is_open": 1 if st.is_open() else 0,
        "half_open": 1 if st.half_open else 0,
        "half_open_attempted": 1 if st.half_open_attempted else 0,
    }

__all__ = [
    "should_skip",
    "record_failure",
    "record_success",
    "reset",
    "breaker_status",
]

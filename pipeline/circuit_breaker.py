"""Circuit breaker léger pour collecteurs avec métriques.

Fonctionnalités minimales compatibles tests:
- _STATES: dict interne exposé pour inspection/reset par tests
- should_skip(name): True si breaker ouvert et fenêtre non expirée (incrémente métriques SKIPS)
- record_failure(name): incrémente échecs et ouvre après seuil (métriques OPEN_TOTAL, state, timestamp)
- record_success(name): remet à zéro les compteurs et ferme si ouvert (métrique RESETS_TOTAL)
- reset(name|None): réinitialise un breaker ou tous

Env:
- BREAKER_FAILURE_THRESHOLD (int, défaut 3)
- BREAKER_OPEN_WINDOW_SECONDS (int, défaut 60)
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import time as _time
from typing import Dict

from .metrics.breakers import (
    CB_LAST_OPEN_TIMESTAMP,
    CB_RESETS_TOTAL,
    CIRCUIT_BREAKER_OPEN_SECONDS,
    CIRCUIT_BREAKER_OPEN_TOTAL,
    CIRCUIT_BREAKER_SKIPS_TOTAL,
    CIRCUIT_BREAKER_STATE,
)


@dataclass
class _BreakerState:
    # Champs compatibles avec certains tests
    fail_count: int = 0
    threshold: int = 3
    window_seconds: int = 60
    open: bool = False
    opened_at: float = 0.0  # epoch seconds


_STATES: Dict[str, _BreakerState] = {}


def _cfg_threshold() -> int:
    try:
        return max(1, int(os.getenv("BREAKER_FAILURE_THRESHOLD", "3")))
    except Exception:
        return 3


def _cfg_window() -> int:
    try:
        return max(1, int(os.getenv("BREAKER_OPEN_WINDOW_SECONDS", "60")))
    except Exception:
        return 60


def _get(name: str) -> _BreakerState:
    st = _STATES.get(name)
    if st is None:
        st = _BreakerState(threshold=_cfg_threshold(), window_seconds=_cfg_window())
        _STATES[name] = st
    return st


def time() -> float:
    """Fournit le temps courant (patchable par tests)."""
    return _time.time()


def should_skip(name: str) -> bool:
    st = _get(name)
    # Ouvre si le compteur d'échecs atteint le seuil (compat tests)
    if (not st.open) and (st.fail_count >= st.threshold):
        st.open = True
        st.opened_at = time()
        try:
            CIRCUIT_BREAKER_OPEN_TOTAL.labels(breaker=name).inc()
            CIRCUIT_BREAKER_STATE.labels(breaker=name).set(1)
            CB_LAST_OPEN_TIMESTAMP.labels(breaker=name).set(st.opened_at)
            CIRCUIT_BREAKER_OPEN_SECONDS.labels(breaker=name).set(0)
        except Exception:
            pass
        return True
    if not st.open:
        return False
    window = st.window_seconds
    now = time()
    if (now - st.opened_at) >= window:
        # Auto-close window expired
        st.open = False
        st.fail_count = 0
        st.opened_at = 0.0
        try:
            CIRCUIT_BREAKER_STATE.labels(breaker=name).set(0)
            CIRCUIT_BREAKER_OPEN_SECONDS.labels(breaker=name).set(0)
        except Exception:
            pass
        return False
    # Still open -> skip
    try:
        CIRCUIT_BREAKER_SKIPS_TOTAL.labels(breaker=name).inc()
        CIRCUIT_BREAKER_STATE.labels(breaker=name).set(1)
        # How long open
        CIRCUIT_BREAKER_OPEN_SECONDS.labels(breaker=name).set(now - st.opened_at)
    except Exception:
        pass
    return True


def record_failure(name: str) -> None:
    st = _get(name)
    st.fail_count += 1
    if not st.open and st.fail_count >= st.threshold:
        st.open = True
        st.opened_at = time()
        try:
            CIRCUIT_BREAKER_OPEN_TOTAL.labels(breaker=name).inc()
            CIRCUIT_BREAKER_STATE.labels(breaker=name).set(1)
            CB_LAST_OPEN_TIMESTAMP.labels(breaker=name).set(st.opened_at)
            CIRCUIT_BREAKER_OPEN_SECONDS.labels(breaker=name).set(0)
        except Exception:
            pass


def record_success(name: str) -> None:
    st = _get(name)
    st.fail_count = 0
    if st.open:
        st.open = False
        st.opened_at = 0.0
        try:
            CB_RESETS_TOTAL.labels(breaker=name).inc()
            CIRCUIT_BREAKER_STATE.labels(breaker=name).set(0)
            CIRCUIT_BREAKER_OPEN_SECONDS.labels(breaker=name).set(0)
        except Exception:
            pass


def reset(name: str | None = None) -> None:
    if name is None:
        for key in list(_STATES.keys()):
            _reset_one(key)
    else:
        _reset_one(name)


def _reset_one(name: str) -> None:
    _STATES[name] = _BreakerState(threshold=_cfg_threshold(), window_seconds=_cfg_window())
    try:
        CIRCUIT_BREAKER_STATE.labels(breaker=name).set(0)
        CIRCUIT_BREAKER_OPEN_SECONDS.labels(breaker=name).set(0)
    except Exception:
        pass


__all__ = [
    "_STATES",
    "should_skip",
    "record_failure",
    "record_success",
    "reset",
]

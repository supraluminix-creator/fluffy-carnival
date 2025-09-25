"""Maintenance unifiée (purge + vacuum conditionnel + planification prochaine exécution).

Objectif:
 - Centraliser la logique de maintenance récurrente.
 - Décider d'un VACUUM seulement si fragmentation au‑delà d'un seuil.
 - Mettre à jour les métriques DB (taille, pages, freelist) après opérations.
 - Exposer un gauge `maintenance_next_run_timestamp` indiquant quand le prochain cycle est prévu.

Stratégie fragmentation:
 - On calcule ratio = freelist_pages / total_pages (déjà instrumenté ailleurs).
 - Si ratio > DB_FRAGMENTATION_VACUUM_THRESHOLD (env, défaut 0.15) alors VACUUM.
 - Forcer VACUUM via env FORCE_VACUUM=1 (prioritaire).

Planification:
 - MAINT_INTERVAL_SECONDS (env, défaut 86400) => prochain run = now + interval.

Tests:
 - Monkeypatch `compute_fragmentation` pour retourner un ratio haut/bas.
 - Monkeypatch `vacuum_and_update_metrics` pour observer appel ou non.

"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

from . import purge_job
from .db_stats import update_db_metrics, vacuum_and_update_metrics
from .metrics import MAINTENANCE_NEXT_RUN_TIMESTAMP

# Type alias
FragmentFn = Callable[[str], tuple[int, int, float]]

with suppress(Exception):  # import facultatif si factorisation future
    pass  # type: ignore


def compute_fragmentation(db_path: str) -> tuple[int, int, float]:  # pragma: no cover - utilisé indirectement
    import sqlite3
    from pathlib import Path
    p = Path(db_path)
    if not p.exists():
        return (0, 0, 0.0)
    conn = sqlite3.connect(p.as_posix())
    try:
        cur = conn.execute("PRAGMA page_count")
        page_count = cur.fetchone()[0]
        cur = conn.execute("PRAGMA freelist_count")
        freelist = cur.fetchone()[0]
        ratio = (freelist / page_count) if page_count else 0.0
        return page_count, freelist, ratio
    finally:
        conn.close()


@dataclass
class MaintenanceResult:
    purged: dict | None
    vacuum_performed: bool
    fragmentation_ratio: float
    next_run_ts: int


def run_maintenance(db_path: str = "data/crypto.db", *,
                    fragmentation_threshold: float | None = None,
                    fragment_fn: FragmentFn = compute_fragmentation,
                    purge: bool = True) -> MaintenanceResult:
    """Exécute un cycle de maintenance.

    Args:
        db_path: chemin base.
        fragmentation_threshold: override du seuil (sinon env DB_FRAGMENTATION_VACUUM_THRESHOLD ou 0.15).
        fragment_fn: injection test.
        purge: exécuter purge des liquidations avant vacuum conditionnel.
    """
    if fragmentation_threshold is None:
        fragmentation_threshold = float(os.getenv("DB_FRAGMENTATION_VACUUM_THRESHOLD", "0.15"))

    force_vacuum = os.getenv("FORCE_VACUUM", "0") == "1"
    interval = int(os.getenv("MAINT_INTERVAL_SECONDS", "86400"))
    now = int(time.time())
    next_run_ts = now + interval

    purged_stats = None
    if purge:
        try:
            purged_stats = purge_job.purge_liquidations(db_path)
        except Exception:  # pragma: no cover
            purged_stats = None

    # Fragmentation check
    vacuum_needed = False
    try:
        _, _, ratio = fragment_fn(db_path)
        vacuum_needed = force_vacuum or (ratio > fragmentation_threshold)
    except Exception:  # pragma: no cover
        ratio = 0.0

    if vacuum_needed:
        vacuum_and_update_metrics(db_path)
    else:
        # Toujours rafraîchir les métriques de base
        update_db_metrics(db_path)

    # Planification prochaine exécution
    try:
        if MAINTENANCE_NEXT_RUN_TIMESTAMP is not None:
            MAINTENANCE_NEXT_RUN_TIMESTAMP.set(next_run_ts)  # type: ignore[union-attr]
    except Exception:  # pragma: no cover
        pass

    return MaintenanceResult(
        purged=purged_stats,
        vacuum_performed=vacuum_needed,
        fragmentation_ratio=ratio,
        next_run_ts=next_run_ts,
    )

__all__ = ["run_maintenance", "MaintenanceResult", "compute_fragmentation"]

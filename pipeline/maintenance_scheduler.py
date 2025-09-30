"""Wrapper APScheduler pour exécuter run_maintenance périodiquement.

Idée: fournir une fonction d'enregistrement simple qui:
 - Ajoute un job cron *ou* interval (selon paramètres) appelant run_maintenance
 - Log une ligne structurée avec résultat (ratio, vacuum, lignes purgées) via structlog
 - Incrémente maintenance_cycles_total (success/error)

Utilisation exemple:
    from apscheduler.schedulers.background import BackgroundScheduler
    from pipeline.maintenance_scheduler import register_maintenance

    sched = BackgroundScheduler(timezone='UTC')
    register_maintenance(sched, db_path='data/crypto.db', trigger='cron', cron="0 4 * * *")
    sched.start()

Fallback: si APScheduler non dispo, la fonction renvoie False.
"""
from __future__ import annotations

import time
from typing import Any

try:
    from apscheduler.schedulers.base import BaseScheduler  # type: ignore
except Exception:  # pragma: no cover
    BaseScheduler = object  # type: ignore

import structlog

from .logging_config import setup_logging
from .maintenance import run_maintenance
from .metrics import MAINTENANCE_CYCLES_TOTAL

logger = structlog.get_logger(__name__)


def _job_wrapper(db_path: str):  # pragma: no cover - exécuté en scheduler réel
    start = time.time()
    status = "success"
    try:
        res = run_maintenance(db_path=db_path)
        logger.info(
            "maintenance_cycle",
            vacuum=res.vacuum_performed,
            fragmentation_ratio=round(res.fragmentation_ratio, 4),
            purged=None if res.purged is None else {k: int(v) for k, v in res.purged.items()},
            next_run_ts=res.next_run_ts,
            duration_s=round(time.time() - start, 3),
        )
        MAINTENANCE_CYCLES_TOTAL.labels(status=status).inc()
    except Exception as exc:  # noqa: BLE001
        status = "error"
        logger.error(
            "maintenance_cycle_error",
            error=str(exc.__class__.__name__),
            msg=str(exc),
            duration_s=round(time.time() - start, 3),
        )
        MAINTENANCE_CYCLES_TOTAL.labels(status=status).inc()
        raise


def register_maintenance(
    scheduler: Any,
    *,
    db_path: str = "data/crypto.db",
    trigger: str = "cron",
    cron: str = "0 4 * * *",
    interval_seconds: int = 86400,
) -> bool:
    """Enregistre un job maintenance dans un scheduler APScheduler.

    Args:
        scheduler: instance APScheduler valide
        db_path: chemin base
        trigger: "cron" ou "interval"
        cron: expression cron (si trigger=cron)
        interval_seconds: période (si trigger=interval)
    Returns:
        bool: True si succès enregistrement.
    """
    setup_logging(simple=True)
    try:
        if trigger == "cron":
            from pipeline.purge_job import _cron_kwargs  # réutilisation parsing simple
            kwargs = _cron_kwargs(cron)
            scheduler.add_job(lambda: _job_wrapper(db_path), trigger="cron", **kwargs, id="maintenance")
        else:
            scheduler.add_job(
                lambda: _job_wrapper(db_path),
                trigger="interval",
                seconds=interval_seconds,
                id="maintenance",
            )
        logger.info(
            "maintenance_job_registered",
            trigger=trigger,
            cron=cron if trigger == "cron" else None,
            interval_seconds=None if trigger == "cron" else interval_seconds,
        )
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("maintenance_job_register_failed", error=str(exc.__class__.__name__), msg=str(exc))
        return False

__all__ = ["register_maintenance"]

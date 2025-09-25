"""Deprecated compatibility shim.

Ce module est conservé uniquement pour compatibilité d'anciens imports
(`from pipeline import db_metrics`). Utiliser désormais `pipeline.db_stats`.
Il ré-exporte les fonctions publiques et émet un avertissement de dépréciation.
"""
from __future__ import annotations

import warnings

from .db_stats import get_db_path, update_db_metrics, vacuum_and_update_metrics

warnings.warn(
    "pipeline.db_metrics est déprécié; utiliser pipeline.db_stats",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["update_db_metrics", "vacuum_and_update_metrics", "get_db_path"]
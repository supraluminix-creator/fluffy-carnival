"""Deprecated shim.

Historique: ancien emplacement de BaseCollector. La version complète et maintenue
se trouve maintenant dans `pipeline.collectors.base_collector`.

Ne plus importer directement ce module; utiliser:
    from pipeline.collectors.base_collector import BaseCollector
"""
from __future__ import annotations

import warnings

from .collectors.base_collector import BaseCollector  # noqa: F401

warnings.warn(
    "pipeline.base_collector est déprécié; utiliser pipeline.collectors.base_collector",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["BaseCollector"]

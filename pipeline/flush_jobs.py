"""Jobs utilitaires pour opérations de maintenance (flush, etc.)."""

from __future__ import annotations

import logging

from . import liquidations_registry

logger = logging.getLogger(__name__)


async def flush_bybit_liquidations() -> dict:
    """Job scheduler: force un flush des liquidations Bybit si writer présent.

    Retourne un petit dict pour visibilité lors d'un export batch (si utilisé).
    """
    ok = await liquidations_registry.flush_if_present()
    if ok:
        logger.info("Flush job: liquidation buffer flushed")
    else:
        logger.debug("Flush job: aucun writer présent (process séparé ou WS non démarré)")
    return {"flushed": ok}

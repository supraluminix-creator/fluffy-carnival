"""Registry global pour le writer des liquidations Bybit.

Permet à un job scheduler d'invoquer un flush explicite sans couplage
fort avec l'instance WS. Si le writer n'est pas présent (process séparé),
le flush job retournera False proprement.
"""
from __future__ import annotations

from typing import Optional

from .collectors.bybit_liquidations import BybitLiquidationsWriter

_writer: Optional[BybitLiquidationsWriter] = None


def set_writer(writer: BybitLiquidationsWriter) -> None:
    """Enregistre le writer courant (idempotent)."""
    global _writer
    _writer = writer


def get_writer() -> Optional[BybitLiquidationsWriter]:  # pragma: no cover - trivial
    return _writer


async def flush_if_present() -> bool:
    """Flush le buffer si un writer est présent.

    Returns:
        bool: True si un flush a été déclenché, False sinon.
    """
    if _writer is None:
        return False
    await _writer.flush()
    return True

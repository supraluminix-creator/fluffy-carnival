"""
DeFi collectors: DefiLlama.
Gère TVL, revenus, fees, utilisateurs actifs.
"""

from typing import Any, TypedDict

import requests


class DefiTVLRecord(TypedDict):
    chain: str
    tvl: float | None
    tvl_prev_day: float | None
    tvl_prev_week: float | None
    tvl_prev_month: float | None


def _to_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):  # pragma: no cover - defensive branch
        return None


def fetch_defillama_tvl(chain: str) -> DefiTVLRecord | None:
    """Récupère un snapshot TVL pour une chaîne via DefiLlama.

    Retourne None si erreur réseau ou schéma inattendu.
    """
    url = f"https://api.llama.fi/v2/chains/{chain}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):  # schéma inattendu
            return None
        return DefiTVLRecord(
            chain=chain,
            tvl=_to_float(data.get("tvl")),
            tvl_prev_day=_to_float(data.get("tvlPrevDay")),
            tvl_prev_week=_to_float(data.get("tvlPrevWeek")),
            tvl_prev_month=_to_float(data.get("tvlPrevMonth")),
        )
    except Exception as e:  # pragma: no cover - chemin d'erreur réseau
        print(f"Erreur fetch_defillama_tvl: {e}")
        return None

__all__ = ["DefiTVLRecord", "fetch_defillama_tvl"]
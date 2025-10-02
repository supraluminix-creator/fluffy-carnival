"""
DeFi collectors: DefiLlama.
Gère TVL, revenus, fees, utilisateurs actifs.
"""

from typing import TypedDict

import requests

from pipeline.utils import to_float


class DefiTVLRecord(TypedDict):
    chain: str
    tvl: float | None
    tvl_prev_day: float | None
    tvl_prev_week: float | None
    tvl_prev_month: float | None



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
        return DefiTVLRecord(  # pragma: no cover - retour direct simple
            chain=chain,
            tvl=to_float(data.get("tvl"), default=None),
            tvl_prev_day=to_float(data.get("tvlPrevDay"), default=None),
            tvl_prev_week=to_float(data.get("tvlPrevWeek"), default=None),
            tvl_prev_month=to_float(data.get("tvlPrevMonth"), default=None),
        )
    except Exception as e:  # pragma: no cover - chemin d'erreur réseau
        print(f"Erreur fetch_defillama_tvl: {e}")
        return None

__all__ = ["DefiTVLRecord", "fetch_defillama_tvl"]
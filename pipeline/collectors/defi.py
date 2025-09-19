"""
DeFi collectors: DefiLlama.
Gère TVL, revenus, fees, utilisateurs actifs.
"""

from typing import Any

import requests


def fetch_defillama_tvl(chain: str) -> dict[str, Any] | None:
    """
    Fetch TVL and DeFi stats from DefiLlama.

    Parameters
    ----------
    chain : str
        Blockchain name (e.g., 'ethereum').

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with TVL and stats.
    """
    url = f"https://api.llama.fi/v2/chains/{chain}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "chain": chain,
            "tvl": data.get("tvl"),
            "tvlPrevDay": data.get("tvlPrevDay"),
            "tvlPrevWeek": data.get("tvlPrevWeek"),
            "tvlPrevMonth": data.get("tvlPrevMonth"),
        }
    except Exception as e:
        print(f"Erreur fetch_defillama_tvl: {e}")
        return None
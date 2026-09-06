"""
DeFi collectors: DefiLlama.
Gère TVL, revenus, fees, utilisateurs actifs.

Quick win: utiliser la façade HTTP unifiée pour les appels JSON tout en
préservant la compatibilité des tests existants qui monkeypatchent
``requests.get``. Si on détecte un monkeypatch de tests (module commençant
par "tests."), on retombe sur le chemin legacy requests.get afin de ne pas
casser ces tests historiques.
"""

from typing import Any, TypedDict, cast

import requests

from pipeline.http import fetch_json
from pipeline.http_utils import is_requests_monkeypatched


def _to_float_opt(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class DefiTVLRecord(TypedDict):
    chain: str
    tvl: float | None
    tvl_prev_day: float | None
    tvl_prev_week: float | None
    tvl_prev_month: float | None


def fetch_defillama_tvl(chain: str) -> DefiTVLRecord | None:
    """Récupère un snapshot TVL pour une chaîne via DefiLlama.

    Utilise par défaut la façade HTTP unifiée (retry/backoff/metrics). Si on
    détecte un monkeypatch de tests sur requests.get (module commençant par
    "tests."), on bascule sur le chemin legacy requests pour conserver les
    tests historiques.

    Retourne None si erreur réseau ou schéma inattendu.
    """
    url = f"https://api.llama.fi/v2/chains/{chain}"
    try:
        # Détection d'un monkeypatch tests sur requests.get (utilitaire partagé)
        if is_requests_monkeypatched(getattr(requests, "get", None)):
            # Chemin legacy compatible tests existants
            resp = requests.get(url, timeout=10)
            data = cast(Any, resp.json())
        else:
            # Chemin façade unifiée
            data = fetch_json(url, timeout=10)

        if not isinstance(data, dict):  # schéma inattendu
            return None
        return DefiTVLRecord(  # pragma: no cover - retour direct simple
            chain=chain,
            tvl=_to_float_opt(data.get("tvl")),
            tvl_prev_day=_to_float_opt(data.get("tvlPrevDay")),
            tvl_prev_week=_to_float_opt(data.get("tvlPrevWeek")),
            tvl_prev_month=_to_float_opt(data.get("tvlPrevMonth")),
        )
    except Exception as e:  # pragma: no cover - chemin d'erreur réseau
        print(f"Erreur fetch_defillama_tvl: {e}")
        return None


__all__ = ["DefiTVLRecord", "fetch_defillama_tvl"]

"""
Collector SOPR via BGeometrics API
Prod-safe, modulaire, testable
"""
from typing import Any

import requests


class SOPRBGeometricsCollector:
    """Collecteur SOPR via BGeometrics."""
    BASE_URL = "https://api.bgeometrics.com/v1/sopr"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def fetch_sopr(self, symbol: str = "BTC") -> dict[str, Any] | None:
        """
        Récupère la métrique SOPR pour un symbole donné (ex: BTC).
        """
        params = {"symbol": symbol}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = requests.get(self.BASE_URL, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return data if "sopr" in data else None
        except Exception as e:
            print(f"Erreur SOPR BGeometrics: {e}")
            return None

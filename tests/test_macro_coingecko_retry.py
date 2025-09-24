import os
import httpx
import pytest
from prometheus_client import generate_latest
from pipeline.collectors.market import fetch_macro_orchestrated

class Dummy429Then200:
    def __init__(self):
        self.calls = 0
    def __call__(self, url, headers=None, params=None, timeout=10):  # sync httpx.get signature
        self.calls += 1
        if self.calls <= 2:
            return DummyResp(429, {"error": "rate limit"})
        # success minimal
        return DummyResp(200, {
            "last_updated": "2025-09-22T00:00:00Z",
            "market_data": {
                "current_price": {"usd": 42000},
                "total_volume": {"usd": 1000000},
                "market_cap": {"usd": 800000000},
                "market_cap_rank": 1
            }
        })
    async def async_call(self, url, headers=None, params=None, timeout=10):  # async AsyncClient.get signature
        # Réutilise la logique sync pour compter les appels et retourner un DummyResp
        return self.__call__(url, headers=headers, params=params, timeout=timeout)

class DummyResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=type("R", (), {"status_code": self.status_code})())

@pytest.mark.asyncio
async def test_coingecko_retry_integration(monkeypatch):
    # Config retry agressive pour test
    monkeypatch.setenv("RETRY_HTTP_ENABLED", "1")
    monkeypatch.setenv("RETRY_HTTP_MAX", "3")
    monkeypatch.setenv("RETRY_HTTP_BACKOFF_BASE", "0.01")
    # Breaker seuil élevé pour ne pas s'ouvrir ici
    monkeypatch.setenv("HTTP_BREAKER_THRESHOLD", "10")
    dummy = Dummy429Then200()
    # Patch ancien chemin sync (héritage) et nouveau chemin async (façade avec AsyncClient)
    monkeypatch.setattr(httpx, 'get', dummy)
    # Patch méthode AsyncClient.get pour le chemin réellement utilisé après migration
    monkeypatch.setattr(httpx.AsyncClient, 'get', lambda self, url, headers=None, params=None, timeout=10: dummy.async_call(url, headers=headers, params=params, timeout=timeout))

    res = await fetch_macro_orchestrated('bitcoin')
    assert res and res.get('source') == 'coingecko'

    # Cherche compteur retry (endpoint label devrait être 'coingecko/coins')
    exposition = generate_latest().decode()
    # Recherche de la ligne attendue.
    target = 'http_retries_total{endpoint="coingecko/coins",reason="RateLimitError"} 2.0'
    assert target in exposition, f'Ligne métrique manquante: {target}\nExposition partielle:\n' + '\n'.join([l for l in exposition.splitlines() if 'http_retries_total' in l])

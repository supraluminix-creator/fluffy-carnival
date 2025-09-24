import os
import httpx
import pytest
from pipeline.collectors.market import fetch_market
from pipeline import http_wrappers

class DummyResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code and self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

@pytest.mark.parametrize("mode", ["primary", "fallback"]) 
def test_market_facade_optin(monkeypatch, mode):
    os.environ["MARKET_USE_FACADE"] = "1"
    # Compteur pour simuler réponses séquentielles
    calls = {"n": 0, "urls": []}

    def fake_retry(url, timeout=None, headers=None, params=None, retries=3, backoff_base=0.01, classify_endpoint=None):  # signature approx
        calls["n"] += 1
        calls["urls"].append(url)
        if mode == "primary":
            # Première URL (coingecko) success immédiat
            if "coingecko" in url:
                return {
                    "market_data": {
                        "current_price": {"usd": 11.0},
                        "total_volume": {"usd": 22.0},
                        "market_cap": {"usd": 33.0},
                        "market_cap_rank": 4,
                    }
                }
        else:  # fallback mode
            # Force échec primaire en levant une exception quand URL coingecko
            if "coingecko" in url:
                raise httpx.RequestError("cg boom")
            if "coinmarketcap" in url:
                return {
                    "data": {"BTCFACADE": {"quote": {"USD": {
                        "price": 99.0,
                        "volume_24h": 199.0,
                        "market_cap": 299.0,
                        "market_cap_dominance": 9.9,
                    }}}}
                }
        # Valeur par défaut si inattendu
        return {"market_data": {"current_price": {"usd": 0}}}

    # Patch uniquement la fonction retry (façade branchera dessus)
    monkeypatch.setattr(http_wrappers, "http_get_json_retry", fake_retry)
    # Pour éviter d'aller vers la version sans retry
    monkeypatch.setenv("RETRY_HTTP_ENABLED", "1")
    monkeypatch.setenv("RETRY_HTTP_MAX", "2")
    sym = "btcfacade" if mode == "fallback" else "btcfacadep"
    rec = fetch_market(sym)
    if mode == "primary":
        assert rec and rec["price"] == 11.0 and rec["dominance"] == 4
        assert any("coingecko" in u for u in calls["urls"]) and not any("coinmarketcap" in u for u in calls["urls"])  # pas de fallback
    else:
        assert rec and rec["price"] == 99.0 and rec["dominance"] == 9.9
        assert any("coingecko" in u for u in calls["urls"]) and any("coinmarketcap" in u for u in calls["urls"])  # fallback pris

    # Nettoyage env
    os.environ.pop("MARKET_USE_FACADE", None)

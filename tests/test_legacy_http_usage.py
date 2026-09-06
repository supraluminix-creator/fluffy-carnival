import os

from prometheus_client import REGISTRY


def test_legacy_http_usage_increments_market(monkeypatch):
    """Vérifie que l'appel legacy (sans façade) incrémente legacy_http_usage_total{collector="market"}.

    Chemin activé en s'assurant que MARKET_USE_FACADE != "1".
    On monkeypatch httpx.get pour éviter tout accès réseau et contrôler la payload.
    """
    # Force mode legacy
    os.environ.pop("MARKET_USE_FACADE", None)

    from pipeline.collectors import market as market_mod

    # Valeur avant
    before = REGISTRY.get_sample_value("legacy_http_usage_total", {"collector": "market"}) or 0.0

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):  # payload minimale attendue par fetch_market
            return {
                "market_data": {
                    "current_price": {"usd": 123.45},
                    "total_volume": {"usd": 1000},
                    "market_cap": {"usd": 999999},
                    "market_cap_rank": 7,
                }
            }

    def fake_get(url, timeout=10):  # signature compatible
        return _Resp()

    monkeypatch.setattr(market_mod.httpx, "get", fake_get)

    # Utiliser un symbole unique pour éviter le cache éventuel sur 'bitcoin'
    result = market_mod.fetch_market("legacytestcoin")
    assert result is not None
    assert result["price"] == 123.45

    after = REGISTRY.get_sample_value("legacy_http_usage_total", {"collector": "market"}) or 0.0
    assert after == before + 1, f"Compteur legacy_http_usage_total non incrémenté (before={before}, after={after})"

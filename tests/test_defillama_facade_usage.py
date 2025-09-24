import asyncio
import os


def test_defillama_uses_async_fetch_json(monkeypatch):
    """Vérifie que DefiLlama passe bien par async_fetch_json (façade) quand retry activé.

    On monkeypatch la fonction pour compter les appels et fournir des réponses factices pour:
      1. /v2/chains
      2. /v2/historicalChainTvl/<chain>
    """
    os.environ["RETRY_HTTP_ENABLED"] = "1"
    os.environ["RETRY_FORCE_THREAD"] = "0"  # s'assurer qu'on ne force pas le chemin threadé

    from pipeline.collectors import defillama as defi_mod

    calls: list[str] = []

    async def fake_async_fetch_json(url: str, *a, **k):  # signature simplifiée
        calls.append(url)
        if url.endswith("/v2/chains"):
            return [
                {"name": "Ethereum", "tvl": 1000000},
                {"name": "Other", "tvl": 50},
            ]
        if "/v2/historicalChainTvl/" in url:
            # Points: timestamp, valeur
            return [
                [int(1_700_000_000), 900000],
                [int(1_700_086_400), 950000],  # ~+1 jour
            ]
        return {}

    monkeypatch.setattr(defi_mod, "async_fetch_json", fake_async_fetch_json)

    async def _run():
        res = await defi_mod.fetch_defillama_tvl("Ethereum", cache_ttl=1)
        assert res is not None
        assert res["value"]["tvl"] == 1000000
        return res

    result = asyncio.run(_run())
    # On attend au moins 2 appels façade (chains + historical)
    assert len(calls) >= 2, f"Nombre d'appels async_fetch_json inattendu: {calls}"
    assert any(c.endswith("/v2/chains") for c in calls)
    assert any("/v2/historicalChainTvl/" in c for c in calls)
    # Vérification basique des champs historiques calculés
    assert "tvlPrevDay" in result["value"]
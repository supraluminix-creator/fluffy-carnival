import asyncio
import os

# Test ciblé: vérifier que la façade (http_get_json_retry interne) est appelée via fetch_macro_orchestrated (tier_coingecko)

def test_facade_used_in_macro_orchestrated(monkeypatch):
    os.environ["RETRY_HTTP_ENABLED"] = "1"
    calls = {"retry": 0}

    # Dummy payload minimal conforme aux attentes du tier coingecko
    dummy_payload = {
        "last_updated": "2025-01-01T00:00:00Z",
        "market_data": {
            "current_price": {"usd": 123.45},
            "total_volume": {"usd": 456.7},
            "market_cap": {"usd": 789.0},
            "market_cap_rank": 1,
        },
    }

    import pipeline.http_wrappers as hw

    def fake_retry(url, **kwargs):  # sync wrapper utilisé par async_fetch_json -> async_http_get_json_retry pour async
        calls["retry"] += 1
        return dummy_payload

    async def fake_async_retry(client, url, **kwargs):
        calls["retry"] += 1
        return dummy_payload

    # Monkeypatch les deux pour robustesse (selon chemin choisi par façade)
    monkeypatch.setattr(hw, "http_get_json_retry", fake_retry)
    monkeypatch.setattr(hw, "async_http_get_json_retry", fake_async_retry)

    from pipeline.collectors.market import fetch_macro_orchestrated

    result = asyncio.run(fetch_macro_orchestrated("bitcoin"))
    assert result is not None
    # Le premier tier (coingecko) devrait suffire -> au moins un appel retry
    assert calls["retry"] >= 1
    # Structure attendue (macro)
    assert result.get("metric_name") == "macro"
    val = result.get("value", {})
    assert "price" in val and val["price"] == 123.45

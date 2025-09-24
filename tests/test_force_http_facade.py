import os
import time


def test_force_http_facade_market(monkeypatch):
    os.environ['FORCE_HTTP_FACADE'] = '1'
    os.environ.pop('MARKET_USE_FACADE', None)

    from pipeline.collectors import market as market_mod

    calls = {}

    def fake_fetch_json(url, timeout=10, **k):
        calls[url] = calls.get(url, 0) + 1
        if 'coingecko' in url:
            return {
                'market_data': {
                    'current_price': {'usd': 10},
                    'total_volume': {'usd': 1000},
                    'market_cap': {'usd': 500000},
                    'market_cap_rank': 5,
                }
            }
        # fallback path (should not être utilisé si primary OK)
        return { 'data': { 'LEGACYTEST': { 'quote': { 'USD': {'price': 11, 'volume_24h': 1100, 'market_cap': 510000} } } } }

    monkeypatch.setattr(market_mod, 'fetch_json', fake_fetch_json)

    res = market_mod.fetch_market('legacytest', cache_ttl=1)
    assert res is not None
    # coingecko primary must have been called
    assert any('coingecko' in k for k in calls.keys())
    # legacy counter ne doit PAS s'incrémenter dans ce chemin: on vérifie qu'aucun log legacy n'a été émis via variable interne
    assert market_mod._LEGACY_MARKET_LOGGED is False


def test_force_http_facade_defillama(monkeypatch):
    # Force désactivation retry normal mais activation façade via FORCE_HTTP_FACADE
    os.environ['RETRY_HTTP_ENABLED'] = '0'
    os.environ['FORCE_HTTP_FACADE'] = '1'

    from pipeline.collectors import defillama as defi_mod

    seen = []

    async def fake_async_fetch_json(url, *a, **k):
        seen.append(url)
        if url.endswith('/v2/chains'):
            return [{ 'name': 'ChainX', 'tvl': 1234 }]
        if '/v2/historicalChainTvl/' in url:
            now = int(time.time())
            return [[now - 86410, 1200]]
        return []

    monkeypatch.setattr(defi_mod, 'async_fetch_json', fake_async_fetch_json)

    import asyncio

    async def _run():
        return await defi_mod.fetch_defillama_tvl('ChainX', cache_ttl=1)

    result = asyncio.run(_run())
    assert result is not None
    assert any(u.endswith('/v2/chains') for u in seen)
    assert any('/v2/historicalChainTvl/' in u for u in seen)
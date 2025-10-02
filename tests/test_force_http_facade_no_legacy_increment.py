import os

import prometheus_client

# Liste des collectors instrumentés par legacy_http_usage_total
COLLECTORS = [
    'market',
    'defillama',
    'binance_spot',
    'binance_oi',
    'binance_funding',
    'deriv_funding',
    'deriv_lsr',
    'sentiment',
    'onchain_txcount','onchain_hashrate','onchain_sopr'
]

# Fonctions d'appel minimales par collector (certaines retournent None acceptables)
async_calls = []

def _call_market():
    from pipeline.collectors import market as m
    return m.fetch_market('bitcoin', cache_ttl=1)

def _call_defillama():
    import asyncio

    from pipeline.collectors import defillama as d
    async def run():
        return await d.fetch_defillama_tvl('Ethereum', cache_ttl=1)
    return asyncio.run(run())

def _call_binance_spot():
    from pipeline.collectors import binance as b
    return b.fetch_binance_spot_price('BTCUSDT')

def _call_binance_oi():
    from pipeline.collectors import binance as b
    return b.fetch_binance_futures_oi('BTCUSDT')

def _call_binance_funding():
    from pipeline.collectors import binance as b
    return b.fetch_binance_funding('BTCUSDT')

async def _call_deriv_funding():
    from pipeline.collectors import derivatives as d
    return await d.fetch_bybit_funding('BTCUSDT')

async def _call_deriv_lsr():
    from pipeline.collectors import derivatives as d
    return await d.fetch_bybit_long_short_ratio('BTCUSDT')

async def _call_sentiment():
    from pipeline.collectors import sentiment as s
    return await s.fetch_fear_greed(cache_ttl=1)

def _call_onchain_txcount():
    from pipeline.collectors import txcount as txc
    return txc.TxCountCollector().fetch_txcount('BTC')

def _call_onchain_hashrate():
    from pipeline.collectors import hashrate as hrc
    return hrc.HashrateCollector().fetch_hashrate('BTC')

def _call_onchain_sopr():
    from pipeline.collectors import sopr as sopr_mod
    return sopr_mod.fetch_sopr(symbol='BTC')


def test_no_legacy_increment_under_force(monkeypatch):
    os.environ['FORCE_HTTP_FACADE'] = '1'
    os.environ.pop('MARKET_USE_FACADE', None)

    # snapshot initial des samples legacy
    registry = prometheus_client.REGISTRY
    before = {}
    for metric in registry.collect():
        if metric.name == 'legacy_http_usage_total':
            for s in metric.samples:
                before[(s.labels.get('collector'))] = s.value

    # Exécuter chaque collector une fois
    _call_market()
    _call_defillama()
    _call_binance_spot()
    _call_binance_oi()
    _call_binance_funding()

    import asyncio
    asyncio.run(_call_deriv_funding())
    asyncio.run(_call_deriv_lsr())
    asyncio.run(_call_sentiment())
    _call_onchain_txcount()
    _call_onchain_hashrate()
    _call_onchain_sopr()

    after = {}
    for metric in registry.collect():
        if metric.name == 'legacy_http_usage_total':
            for s in metric.samples:
                after[(s.labels.get('collector'))] = s.value

    # Vérifier que les valeurs n'ont pas augmenté
    for c in COLLECTORS:
        if c in before and c in after:
            assert after[c] == before[c], f"legacy counter incremented for {c} under forced facade"

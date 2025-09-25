import os

import prometheus_client

COLLECTORS = [
    'market','defillama','binance_spot','binance_oi','binance_funding','deriv_funding','deriv_lsr','sentiment',
    'onchain_txcount','onchain_hashrate','onchain_sopr'
]

def _invoke_all():
    from pipeline.collectors import binance, defillama, derivatives, market, sentiment
    market.fetch_market('bitcoin', cache_ttl=1)
    import asyncio
    async def run_async():
        await defillama.get_chain_data('Ethereum')
        await defillama.get_historical_chain_data('Ethereum')
        await derivatives.fetch_bybit_funding('BTCUSDT')
        await derivatives.fetch_bybit_long_short_ratio('BTCUSDT')
        await sentiment.fetch_fear_greed(cache_ttl=1)
    asyncio.run(run_async())
    binance.fetch_binance_spot_price('BTCUSDT')
    binance.fetch_binance_futures_oi('BTCUSDT')
    binance.fetch_binance_funding('BTCUSDT')
    from pipeline.collectors import hashrate as hrc
    from pipeline.collectors import sopr as sopr_mod
    from pipeline.collectors import txcount as txc
    txc.TxCountCollector().fetch_txcount('BTC')
    hrc.HashrateCollector().fetch_hashrate('BTC')
    sopr_mod.fetch_sopr(symbol='BTC')

def test_no_leak_gauge_under_forced():
    os.environ['FORCE_HTTP_FACADE'] = '1'
    os.environ.pop('MARKET_USE_FACADE', None)
    _invoke_all()
    leak = {}
    for fam in prometheus_client.REGISTRY.collect():
        if fam.name == 'facade_forced_leak':
            for s in fam.samples:
                leak[s.labels['collector']] = s.value
    for c in COLLECTORS:
        assert c in leak, f"missing facade_forced_leak sample for {c}"
        assert leak[c] == 0, f"collector {c} leak gauge should remain 0 (got {leak[c]!r})"
import os
import prometheus_client

COLLECTORS = [
    'market','defillama','binance_spot','binance_oi','binance_funding','deriv_funding','deriv_lsr','sentiment',
    'onchain_txcount','onchain_hashrate','onchain_sopr'
]

def _invoke_one_per_collector():
    from pipeline.collectors import market, defillama, binance, derivatives, sentiment
    # market
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
    from pipeline.collectors import txcount as txc, hashrate as hrc, sopr as sopr_mod
    txc.TxCountCollector().fetch_txcount('BTC')
    hrc.HashrateCollector().fetch_hashrate('BTC')
    sopr_mod.fetch_sopr(symbol='BTC')


def test_facade_dry_run_sets_gauge_without_forcing():
    os.environ['DRY_RUN_FACADE'] = '1'
    os.environ.pop('FORCE_HTTP_FACADE', None)
    os.environ.pop('MARKET_USE_FACADE', None)
    _invoke_one_per_collector()
    dry = {}
    forced = {}
    for fam in prometheus_client.REGISTRY.collect():
        if fam.name == 'facade_dry_run':
            for s in fam.samples:
                dry[s.labels['collector']] = s.value
        if fam.name == 'facade_forced':
            for s in fam.samples:
                forced[s.labels['collector']] = s.value
    for c in COLLECTORS:
        assert dry.get(c) in (0,1), f"missing dry-run sample for {c}"
        assert dry.get(c) == 1, f"collector {c} should have facade_dry_run=1 in DRY_RUN_FACADE mode"
        assert forced.get(c,0) == 0, f"collector {c} should have facade_forced=0 in DRY_RUN_FACADE mode"

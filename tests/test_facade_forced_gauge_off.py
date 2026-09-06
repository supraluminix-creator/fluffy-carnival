import os

import prometheus_client

COLLECTORS = [
    "market",
    "defillama",
    "binance_spot",
    "binance_oi",
    "binance_funding",
    "deriv_funding",
    "deriv_lsr",
    "sentiment",
    "onchain_txcount",
    "onchain_hashrate",
    "onchain_sopr",
]


def _invoke_all():
    from pipeline.collectors import binance, defillama, derivatives, market

    # Market (sync)
    market.fetch_market("bitcoin", cache_ttl=1)
    import asyncio

    async def _run_async():
        await defillama.get_chain_data("Ethereum")  # ensures gauge set path
        await defillama.get_historical_chain_data("Ethereum")
        await derivatives.fetch_bybit_funding("BTCUSDT")
        await derivatives.fetch_bybit_long_short_ratio("BTCUSDT")
        from pipeline.collectors import sentiment

        await sentiment.fetch_fear_greed(cache_ttl=1)

    asyncio.run(_run_async())
    binance.fetch_binance_spot_price("BTCUSDT")
    binance.fetch_binance_futures_oi("BTCUSDT")
    binance.fetch_binance_funding("BTCUSDT")
    # Onchain
    from pipeline.collectors import hashrate as hrc
    from pipeline.collectors import sopr as sopr_mod
    from pipeline.collectors import txcount as txc

    txc.TxCountCollector().fetch_txcount("BTC")
    hrc.HashrateCollector().fetch_hashrate("BTC")
    sopr_mod.fetch_sopr(symbol="BTC")


def test_facade_forced_gauge_off():
    # Assure mode non forcé
    os.environ.pop("FORCE_HTTP_FACADE", None)
    os.environ.pop("MARKET_USE_FACADE", None)
    _invoke_all()
    values = {}
    for fam in prometheus_client.REGISTRY.collect():
        if fam.name == "facade_forced":
            for s in fam.samples:
                values[s.labels["collector"]] = s.value
    for c in COLLECTORS:
        assert c in values, f"missing facade_forced sample for {c}"
        assert values[c] == 0, f"collector {c} should have facade_forced=0 when not forced (got {values[c]!r})"

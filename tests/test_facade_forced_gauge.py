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

    market.fetch_market("bitcoin", cache_ttl=1)
    import asyncio

    async def _run_defi():
        await defillama.fetch_defillama_tvl("Ethereum", cache_ttl=1)
        from pipeline.collectors import sentiment

        await sentiment.fetch_fear_greed(cache_ttl=1)

    asyncio.run(_run_defi())
    binance.fetch_binance_spot_price("BTCUSDT")
    binance.fetch_binance_futures_oi("BTCUSDT")
    binance.fetch_binance_funding("BTCUSDT")

    async def _run_deriv():
        await derivatives.fetch_bybit_funding("BTCUSDT")
        await derivatives.fetch_bybit_long_short_ratio("BTCUSDT")

    asyncio.run(_run_deriv())
    # Onchain collectors
    from pipeline.collectors import hashrate as hrc
    from pipeline.collectors import sopr as sopr_mod
    from pipeline.collectors import txcount as txc

    # Utilise chemins sync pour simplicité
    txc.TxCountCollector().fetch_txcount("BTC")
    hrc.HashrateCollector().fetch_hashrate("BTC")
    sopr_mod.fetch_sopr(symbol="BTC")


def test_facade_forced_gauge():
    os.environ["FORCE_HTTP_FACADE"] = "1"
    os.environ.pop("MARKET_USE_FACADE", None)
    _invoke_all()
    forced = {}
    for m in prometheus_client.REGISTRY.collect():
        if m.name == "facade_forced":
            for s in m.samples:
                forced[s.labels["collector"]] = s.value
    for c in COLLECTORS:
        assert forced.get(c) in (0, 1), f"missing gauge sample for {c}"
        # En mode forced, market peut renvoyer 1, les autres aussi => on exige 1
        assert forced.get(c) == 1, f"collector {c} should have facade_forced=1 when FORCE_HTTP_FACADE=1"

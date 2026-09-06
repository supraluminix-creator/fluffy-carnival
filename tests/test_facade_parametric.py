import asyncio
import os

import prometheus_client
import pytest

# Paramétrisation centralisée des collectors et de leur mode (sync/async)
COLLECTOR_CALLS = {
    "market": lambda: __import__("pipeline.collectors.market", fromlist=["fetch_market"]).fetch_market(
        "bitcoin", cache_ttl=1
    ),
    "defillama": lambda: asyncio.run(
        __import__("pipeline.collectors.defillama", fromlist=["get_chain_data"]).get_chain_data("Ethereum")
    ),
    "binance_spot": lambda: __import__(
        "pipeline.collectors.binance", fromlist=["fetch_binance_spot_price"]
    ).fetch_binance_spot_price("BTCUSDT"),
    "binance_oi": lambda: __import__(
        "pipeline.collectors.binance", fromlist=["fetch_binance_futures_oi"]
    ).fetch_binance_futures_oi("BTCUSDT"),
    "binance_funding": lambda: __import__(
        "pipeline.collectors.binance", fromlist=["fetch_binance_funding"]
    ).fetch_binance_funding("BTCUSDT"),
    "deriv_funding": lambda: asyncio.run(
        __import__("pipeline.collectors.derivatives", fromlist=["fetch_bybit_funding"]).fetch_bybit_funding("BTCUSDT")
    ),
    "deriv_lsr": lambda: asyncio.run(
        __import__(
            "pipeline.collectors.derivatives", fromlist=["fetch_bybit_long_short_ratio"]
        ).fetch_bybit_long_short_ratio("BTCUSDT")
    ),
    "sentiment": lambda: asyncio.run(
        __import__("pipeline.collectors.sentiment", fromlist=["fetch_fear_greed"]).fetch_fear_greed(cache_ttl=1)
    ),
    "onchain_txcount": lambda: __import__("pipeline.collectors.txcount", fromlist=["TxCountCollector"])
    .TxCountCollector()
    .fetch_txcount("BTC"),
    "onchain_hashrate": lambda: __import__("pipeline.collectors.hashrate", fromlist=["HashrateCollector"])
    .HashrateCollector()
    .fetch_hashrate("BTC"),
    "onchain_sopr": lambda: __import__("pipeline.collectors.sopr", fromlist=["fetch_sopr"]).fetch_sopr(symbol="BTC"),
}


@pytest.mark.parametrize("collector", COLLECTOR_CALLS.keys())
def test_parametric_facade_forced_modes(collector):
    os.environ["FORCE_HTTP_FACADE"] = "1"
    os.environ.pop("DRY_RUN_FACADE", None)
    os.environ.pop("MARKET_USE_FACADE", None)
    COLLECTOR_CALLS[collector]()
    forced = prometheus_client.REGISTRY.get_sample_value("facade_forced", {"collector": collector})
    assert forced == 1, f"facade_forced should be 1 for {collector} in forced mode"


@pytest.mark.parametrize("collector", COLLECTOR_CALLS.keys())
def test_parametric_facade_dry_run_modes(collector):
    os.environ.pop("FORCE_HTTP_FACADE", None)
    os.environ["DRY_RUN_FACADE"] = "1"
    os.environ.pop("MARKET_USE_FACADE", None)
    COLLECTOR_CALLS[collector]()
    dry = prometheus_client.REGISTRY.get_sample_value("facade_dry_run", {"collector": collector})
    forced = prometheus_client.REGISTRY.get_sample_value("facade_forced", {"collector": collector}) or 0
    assert dry == 1, f"facade_dry_run should be 1 for {collector} in dry-run"
    assert forced == 0, f"facade_forced should remain 0 for {collector} in dry-run"


@pytest.mark.parametrize("collector", COLLECTOR_CALLS.keys())
def test_parametric_facade_normal_modes(collector):
    os.environ.pop("FORCE_HTTP_FACADE", None)
    os.environ.pop("DRY_RUN_FACADE", None)
    os.environ.pop("MARKET_USE_FACADE", None)
    COLLECTOR_CALLS[collector]()
    dry = prometheus_client.REGISTRY.get_sample_value("facade_dry_run", {"collector": collector}) or 0
    forced = prometheus_client.REGISTRY.get_sample_value("facade_forced", {"collector": collector}) or 0
    assert forced == 0, f"facade_forced should be 0 for {collector} in normal mode"
    assert dry == 0, f"facade_dry_run should be 0 for {collector} in normal mode"

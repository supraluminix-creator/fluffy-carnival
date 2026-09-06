"""Prometheus metrics dedicated to whale balance tracking."""

from __future__ import annotations

from typing import cast

from prometheus_client import REGISTRY as GLOBAL_REGISTRY
from prometheus_client import Gauge


def _gauge(name: str, doc: str, labelnames: list[str]) -> Gauge:
    try:
        return Gauge(name, doc, labelnames)
    except ValueError:
        return cast(Gauge, GLOBAL_REGISTRY._names_to_collectors.get(name))


WHALE_BALANCE_TOTAL = _gauge(
    "whale_balance_total_eth",
    "Total ETH balance aggregated per whale data source",
    ["source"],
)
WHALE_BALANCE_PER_ADDRESS = _gauge(
    "whale_balance_address_eth",
    "ETH balance for an individual tracked address",
    ["source", "address"],
)
WHALE_BALANCE_LAST_UPDATED = _gauge(
    "whale_balance_last_updated_timestamp",
    "Epoch timestamp (seconds) of the latest whale balance refresh",
    ["source"],
)

WHALE_HYPERLIQUID_POSITION_NOTIONAL = _gauge(
    "whale_hyperliquid_position_notional_usd",
    "USD notional size per tracked Hyperliquid position",
    ["trader", "symbol", "side"],
)

WHALE_HYPERLIQUID_POSITION_LEVERAGE = _gauge(
    "whale_hyperliquid_position_leverage",
    "Reported leverage per tracked Hyperliquid position",
    ["trader", "symbol", "side"],
)

WHALE_HYPERLIQUID_LAST_UPDATED = _gauge(
    "whale_hyperliquid_last_updated_timestamp",
    "Epoch timestamp (seconds) of the latest Hyperliquid whale refresh",
    ["trader"],
)

__all__ = [
    "WHALE_BALANCE_TOTAL",
    "WHALE_BALANCE_PER_ADDRESS",
    "WHALE_BALANCE_LAST_UPDATED",
    "WHALE_HYPERLIQUID_LAST_UPDATED",
    "WHALE_HYPERLIQUID_POSITION_LEVERAGE",
    "WHALE_HYPERLIQUID_POSITION_NOTIONAL",
]

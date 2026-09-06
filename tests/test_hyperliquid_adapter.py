from __future__ import annotations

from pathlib import Path

import pytest

from integrations.hyperliquid_adapter import (
    HyperliquidConfig,
    HyperliquidWatcher,
    fetch_positions,
    reset_hyperliquid_metric_state,
)
from pipeline.metrics.whales import (
    WHALE_HYPERLIQUID_LAST_UPDATED,
    WHALE_HYPERLIQUID_POSITION_LEVERAGE,
    WHALE_HYPERLIQUID_POSITION_NOTIONAL,
)


@pytest.mark.asyncio
async def test_fetch_positions_normalizes_payload(tmp_path: Path) -> None:
    cfg = HyperliquidConfig(
        enabled=True,
        api_base="https://api.hyperliquid.xyz/info",
        timeout=5.0,
        cache_ttl=0,
        watchlist=[HyperliquidWatcher(address="0xc2", user_id="19D5")],
        export_dir=tmp_path,
        min_notional_alert=10_000_000.0,
    )

    async def fake_fetcher(_, watcher: HyperliquidWatcher) -> dict[str, object]:
        assert watcher.user_id == "19D5"
        return {
            "positions": [
                {
                    "coin": "BTC",
                    "positionValue": "1000000",
                    "leverage": "25",
                    "side": "short",
                    "entryPrice": "64000",
                    "size": "15.6",
                    "unrealizedPnl": "120000",
                },
                {
                    "coin": "ETH",
                    "usdValue": 500000,
                    "leverage": 12,
                    "side": "long",
                    "entryPrice": 2200,
                    "size": 230.5,
                },
            ],
            "marginSummary": {
                "totalPosValue": "1500000",
                "totalUnrealizedPnl": "120000",
            },
        }

    reset_hyperliquid_metric_state()
    records = await fetch_positions(cfg, fetcher=fake_fetcher, now_ts=1_700_000_000)

    assert len(records) == 5  # two positions * (notional + leverage) + summary
    btc_record = next(r for r in records if r["symbol"] == "BTC" and r["metric_name"] == "hl_position_notional_usd")
    assert btc_record["value"] == pytest.approx(1_000_000.0)
    assert btc_record["metadata"]["side"] == "short"

    pnl_record = next(r for r in records if r["metric_name"] == "hl_total_unrealized_pnl")
    assert pnl_record["value"] == pytest.approx(120_000.0)

    gauge_notional = WHALE_HYPERLIQUID_POSITION_NOTIONAL.labels(trader="19d5", symbol="BTC", side="short")
    assert gauge_notional._value.get() == pytest.approx(1_000_000.0)

    gauge_leverage = WHALE_HYPERLIQUID_POSITION_LEVERAGE.labels(trader="19d5", symbol="BTC", side="short")
    assert gauge_leverage._value.get() == pytest.approx(25.0)

    last_updated = WHALE_HYPERLIQUID_LAST_UPDATED.labels(trader="19d5")
    assert last_updated._value.get() == pytest.approx(1_700_000_000.0)


@pytest.mark.asyncio
async def test_fetch_positions_handles_empty_payload(tmp_path: Path) -> None:
    cfg = HyperliquidConfig(
        enabled=True,
        api_base="https://api.hyperliquid.xyz/info",
        timeout=5.0,
        cache_ttl=0,
        watchlist=[HyperliquidWatcher(address="0xc2")],
        export_dir=tmp_path,
        min_notional_alert=10_000_000.0,
    )

    async def fake_fetcher(*_) -> dict[str, object]:
        return {}

    reset_hyperliquid_metric_state()
    records = await fetch_positions(cfg, fetcher=fake_fetcher, now_ts=1_700_000_000)

    assert len(records) == 1
    assert records[0]["metric_name"] == "hl_total_unrealized_pnl"
    assert records[0]["value"] == pytest.approx(0.0)

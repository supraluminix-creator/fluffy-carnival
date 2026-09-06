from __future__ import annotations

from pathlib import Path

import pytest

from integrations.etherscan_adapter import EtherscanConfig
from integrations.hyperliquid_adapter import HyperliquidConfig, HyperliquidWatcher
from pipeline.collectors import whale_insider


@pytest.mark.asyncio
async def test_whale_insider_snapshot_combines_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    hl_cfg = HyperliquidConfig(
        enabled=True,
        api_base="https://api.hyperliquid.xyz/info",
        timeout=5.0,
        cache_ttl=0,
        watchlist=[HyperliquidWatcher(address="0xc2", user_id="19D5")],
        export_dir=tmp_path,
        min_notional_alert=10_000_000.0,
    )
    es_cfg = EtherscanConfig(
        enabled=True,
        api_key=None,
        addresses=["0xc2"],
        threshold_eth=100.0,
        start_block=0,
        end_block=9_999_999,
        sleep_ms=0,
        export_dir=tmp_path,
    )

    async def fake_collect_balance(_: EtherscanConfig) -> dict[str, object]:
        return {
            "timestamp": 1_700_000_000,
            "metric_name": "insider_whale_balance_total",
            "value": 12_345.6,
            "source": "etherscan",
        }

    async def fake_fetch_positions(_: HyperliquidConfig) -> list[dict[str, object]]:
        return [
            {
                "timestamp": 1_700_000_000,
                "chain": "hyperliquid",
                "trader": "19d5",
                "symbol": "BTC",
                "metric_name": "hl_position_notional_usd",
                "value": 1_000_000.0,
                "source": "hyperliquid",
                "metadata": {"side": "short", "leverage": 25},
            }
        ]

    monkeypatch.setattr(whale_insider, "load_hyperliquid_config", lambda: hl_cfg)
    monkeypatch.setattr(whale_insider, "load_etherscan_config", lambda: es_cfg)
    monkeypatch.setattr(whale_insider, "collect_balance_records", fake_collect_balance)
    monkeypatch.setattr(whale_insider, "fetch_positions", fake_fetch_positions)

    result = await whale_insider.fetch_whale_insider_snapshot()
    assert result is not None
    assert len(result["records"]) == 2
    assert result["meta"]["hyperliquid_records"] == 1
    snapshot_path = tmp_path / "whale_insider_snapshot.json"
    assert snapshot_path.exists()
    loaded = whale_insider.load_latest_snapshot(hl_cfg)
    assert loaded is not None
    assert loaded["meta"]["records_count"] == 2

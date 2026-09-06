from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from integrations import etherscan_adapter
from pipeline.metrics.whales import (
    WHALE_BALANCE_LAST_UPDATED,
    WHALE_BALANCE_PER_ADDRESS,
    WHALE_BALANCE_TOTAL,
)


@pytest.mark.asyncio
async def test_collect_balance_records(monkeypatch, tmp_path: Path):
    etherscan_adapter.reset_whale_metric_state()
    cfg = etherscan_adapter.EtherscanConfig(
        enabled=True,
        api_key="k",
        addresses=["0xAAA", "0xBBB", "0xCCC"],
        threshold_eth=10.0,
        start_block=0,
        end_block=10,
        sleep_ms=0,
        export_dir=tmp_path,
    )

    async def fake_fetch(url: str, params: dict[str, str], timeout: float = 0.0, client=None):
        assert params["module"] == "account"
        assert params["action"] == "balancemulti"
        chunk = params["address"].split(",")
        result = []
        for idx, address in enumerate(chunk, start=1):
            result.append({"account": address, "balance": str(idx * 10**18)})
        return {"status": "1", "result": result}

    monkeypatch.setattr(etherscan_adapter, "async_fetch_json", fake_fetch)

    written: dict[str, Any] = {}

    def fake_write(payload: dict[str, Any], *, cfg, filename=None):
        nonlocal written
        written = payload
        return tmp_path / (filename or "balance.json")

    monkeypatch.setattr(etherscan_adapter, "write_export", fake_write)

    monkeypatch.setattr(etherscan_adapter, "time", lambda: 1_700_000_000)

    record = await etherscan_adapter.collect_balance_records(cfg)
    assert record is not None
    assert record["metric_name"] == "insider_whale_balance_total"
    # 3 addresses => 1 + 2 + 3 ETH
    assert pytest.approx(record["value"], rel=1e-6) == 6.0
    assert "addresses" in record
    assert len(record["addresses"]) == 3
    # payload stored
    assert "addresses" in written
    stored_addresses = written["addresses"]
    assert isinstance(stored_addresses, list)
    assert len(stored_addresses) == 3
    gauge_total = WHALE_BALANCE_TOTAL.labels(source="etherscan")
    assert pytest.approx(gauge_total._value.get(), rel=1e-6) == 6.0  # type: ignore[attr-defined]
    gauge_ts = WHALE_BALANCE_LAST_UPDATED.labels(source="etherscan")
    assert gauge_ts._value.get() == 1_700_000_000  # type: ignore[attr-defined]
    metric_samples = list(WHALE_BALANCE_PER_ADDRESS.collect())[0].samples
    per_address = {
        sample.labels["address"]: sample.value
        for sample in metric_samples
        if sample.name == "whale_balance_address_eth" and sample.labels.get("source") == "etherscan"
    }
    assert per_address["0xaaa"] == pytest.approx(1.0, rel=1e-6)
    assert per_address["0xbbb"] == pytest.approx(2.0, rel=1e-6)
    assert per_address["0xccc"] == pytest.approx(3.0, rel=1e-6)


@pytest.mark.asyncio
async def test_fetch_eth_whale_balances_collector(monkeypatch):
    from pipeline.collectors import whales

    etherscan_adapter.reset_whale_metric_state()
    cfg = etherscan_adapter.EtherscanConfig(
        enabled=True,
        api_key="k",
        addresses=["0x111"],
        threshold_eth=10.0,
        start_block=0,
        end_block=10,
        sleep_ms=0,
        export_dir=Path("exports"),
    )

    async def fake_collect(_cfg):
        return {
            "timestamp": 123,
            "asset": "ETH",
            "symbol": "ETH",
            "chain": "ethereum",
            "metric_name": "insider_whale_balance_total",
            "value": 1.23,
            "source": "etherscan",
            "confidence_score": 1.0,
            "addresses": [{"address": "0x111", "balance_eth": 1.23}],
            "metadata": {"address_count": 1},
        }

    monkeypatch.setenv("ENABLE_WHALE_BALANCES", "1")
    monkeypatch.setenv("ETHERSCAN_ENABLED", "1")
    monkeypatch.setattr(whales, "load_config", lambda: cfg)
    monkeypatch.setattr(whales, "collect_balance_records", fake_collect)

    record = await whales.fetch_eth_whale_balances()
    assert record is not None
    assert record["value"] == 1.23
    assert "addresses" in record


@pytest.mark.asyncio
async def test_collect_balance_records_removes_stale_metrics(monkeypatch, tmp_path: Path):
    etherscan_adapter.reset_whale_metric_state()

    cfg = etherscan_adapter.EtherscanConfig(
        enabled=True,
        api_key="k",
        addresses=["0xAAA", "0xBBB"],
        threshold_eth=10.0,
        start_block=0,
        end_block=10,
        sleep_ms=0,
        export_dir=tmp_path,
    )

    responses = [
        [
            {"account": "0xAAA", "balance": str(1 * 10**18)},
            {"account": "0xBBB", "balance": str(2 * 10**18)},
        ],
        [
            {"account": "0xBBB", "balance": str(3 * 10**18)},
        ],
    ]

    async def fake_fetch_balances(_addresses, _cfg):
        if responses:
            return responses.pop(0)
        return []

    monkeypatch.setattr(etherscan_adapter, "_fetch_balances", fake_fetch_balances)

    def fake_write(payload: dict[str, Any], *, cfg, filename=None):
        _ = payload, cfg
        return tmp_path / (filename or "balance.json")

    monkeypatch.setattr(etherscan_adapter, "write_export", fake_write)
    monkeypatch.setattr(etherscan_adapter, "time", lambda: 1_700_000_000)

    first = await etherscan_adapter.collect_balance_records(cfg)
    assert first is not None
    metric_samples_first = list(WHALE_BALANCE_PER_ADDRESS.collect())[0].samples
    per_address_first = {
        sample.labels["address"]: sample.value
        for sample in metric_samples_first
        if sample.name == "whale_balance_address_eth" and sample.labels.get("source") == "etherscan"
    }
    assert "0xaaa" in per_address_first
    assert "0xbbb" in per_address_first

    second = await etherscan_adapter.collect_balance_records(cfg)
    assert second is not None
    metric_samples_second = list(WHALE_BALANCE_PER_ADDRESS.collect())[0].samples
    per_address_second = {
        sample.labels["address"]: sample.value
        for sample in metric_samples_second
        if sample.name == "whale_balance_address_eth" and sample.labels.get("source") == "etherscan"
    }
    assert "0xaaa" not in per_address_second
    assert per_address_second["0xbbb"] == pytest.approx(3.0, rel=1e-6)

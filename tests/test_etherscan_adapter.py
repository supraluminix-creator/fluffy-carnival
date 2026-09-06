from __future__ import annotations

import pytest

from integrations import etherscan_adapter


@pytest.mark.asyncio
async def test_collect_whale_events_filters_by_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = etherscan_adapter.EtherscanConfig(
        enabled=True,
        api_key="test",
        addresses=["0xabc"],
        threshold_eth=500.0,
        start_block=0,
        end_block=99999999,
        sleep_ms=0,
        export_dir=etherscan_adapter.Path("exports/test"),
    )

    sample_txs = [
        {
            "hash": "0x1",
            "blockNumber": "100",
            "timeStamp": "1700000000",
            "from": "0xAbC",
            "to": "0xdef",
            "value": str(800 * etherscan_adapter._WEI_IN_ETH),
            "gasPrice": "1000000000",
            "txreceipt_status": "1",
        },
        {
            "hash": "0x2",
            "blockNumber": "101",
            "timeStamp": "1700000100",
            "from": "0xabc",
            "to": "0xghi",
            "value": str(100 * etherscan_adapter._WEI_IN_ETH),
            "gasPrice": "1000000000",
            "txreceipt_status": "1",
        },
    ]

    async def fake_fetch(address: str, _: etherscan_adapter.EtherscanConfig) -> list[dict[str, str]]:
        assert address == "0xabc"
        return sample_txs

    monkeypatch.setattr(etherscan_adapter, "_fetch_transactions", fake_fetch)

    payload = await etherscan_adapter.collect_whale_events(cfg)

    assert payload["count"] == 1
    event = payload["events"][0]
    assert event["hash"] == "0x1"
    assert event["direction"] == "out"
    assert pytest.approx(event["value_eth"], rel=1e-6) == 800.0

    # Ensure export writes JSON
    path = etherscan_adapter.write_export(payload, cfg=cfg, filename="test.json")
    assert path.exists()
    data = path.read_text(encoding="utf-8")
    assert "0x1" in data

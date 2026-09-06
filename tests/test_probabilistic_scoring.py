from __future__ import annotations

import pandas as pd
import pytest

from pipeline.scoring import probabilistic


@pytest.mark.asyncio
async def test_score_asset_computes_weighted_score(monkeypatch: pytest.MonkeyPatch) -> None:
    timestamps = pd.date_range("2024-01-01", periods=6, freq="D", tz="UTC")
    prices = [43000, 43200, 42950, 43500, 43800, 44000]
    market_chart = pd.DataFrame({"timestamp": timestamps, "price": prices})

    async def fake_market_chart(**_: object) -> pd.DataFrame:
        return market_chart

    async def fake_coinalyze_snapshot(**_: object) -> dict[str, object]:
        return {"data": {"volume24h": "85000000", "fundingRate": "0.0006"}}

    async def fake_coindesk_orderbook(**_: object) -> dict[str, object]:
        return {"bids": [[43000, 120]], "asks": [[43100, 80]]}

    monkeypatch.setattr(probabilistic, "fetch_coingecko_market_chart", fake_market_chart)
    monkeypatch.setattr(probabilistic, "fetch_coinalyze_snapshot", fake_coinalyze_snapshot)
    monkeypatch.setattr(probabilistic, "fetch_coindesk_orderbook", fake_coindesk_orderbook)

    whale_events = [
        {"direction": "in", "value_usd": 5_000_000},
        {"direction": "out", "value_usd": 4_000_000},
    ]

    report = await probabilistic.score_asset(
        "BTC",
        coinalyze_market="BTCUSDT",
        coinalyze_api_key="dummy",
        coindesk_symbol="BTC-USD",
        coindesk_api_key="dummy",
        whale_events=whale_events,
        days=5,
    )

    assert report.symbol == "BTC"
    assert report.coingecko_id == "bitcoin"
    assert 0.0 <= report.score <= 1.0
    assert report.components.volatility_annualized is not None
    assert report.components.orderbook_imbalance is not None
    assert isinstance(report.strategy, str) and report.strategy


@pytest.mark.asyncio
async def test_score_asset_includes_rumour_context(monkeypatch: pytest.MonkeyPatch) -> None:
    timestamps = pd.date_range("2024-01-01", periods=6, freq="D", tz="UTC")
    prices = [43000, 43200, 42950, 43500, 43800, 44000]
    market_chart = pd.DataFrame({"timestamp": timestamps, "price": prices})

    async def fake_market_chart(**_: object) -> pd.DataFrame:
        return market_chart

    monkeypatch.setattr(probabilistic, "fetch_coingecko_market_chart", fake_market_chart)
    monkeypatch.setattr(probabilistic, "fetch_coinalyze_snapshot", lambda **_: {"data": {}})
    monkeypatch.setattr(probabilistic, "fetch_coindesk_orderbook", lambda **_: {"bids": [], "asks": []})

    rumour_records = [
        {
            "symbol": "BTC",
            "topic": "AI tokens",
            "value": 0.72,
            "confidence": 0.8,
            "sentiment": "positive",
        },
        {
            "symbol": "BTC",
            "topic": "AI tokens",
            "value": 0.68,
            "confidence": 0.75,
            "sentiment": "positive",
        },
    ]

    report = await probabilistic.score_asset("BTC", rumour_records=rumour_records)

    assert report.components.rumour_intensity_index is not None
    assert "rumour_signal" in report.context
    assert report.context.get("rumour_confidence") is not None

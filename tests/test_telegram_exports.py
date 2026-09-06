import builtins
import types

import pytest

try:
    from pipeline.telegram_bot import (
        DefiSnapshot,
        DerivativesSnapshot,
        MarketSnapshot,
        OnChainSnapshot,
        WhaleAlert,
        _snapshot_to_csv,
        _snapshot_to_parquet,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency guard
    pytest.skip(f"telegram dependencies missing: {exc}", allow_module_level=True)


@pytest.fixture
def sample_snapshot() -> MarketSnapshot:
    alerts = [
        WhaleAlert(
            timestamp=1,
            symbol="BTC",
            amount_usd=1_000_000.0,
            transaction_type="transfer",
            source="primary",
            description="Large transfer",
            severity="high",
            confidence=0.9,
        ),
        WhaleAlert(
            timestamp=2,
            symbol="BTC",
            amount_usd=750_000.0,
            transaction_type="transfer",
            source="secondary",
            description="Another transfer",
            severity="medium",
            confidence=0.8,
        ),
    ]
    derivatives = DerivativesSnapshot(
        open_interest=150_000_000.0,
        oi_source="bybit",
        funding_rate=0.0005,
        funding_source="bybit",
        long_short_ratio={"buy_ratio": 0.55, "sell_ratio": 0.45},
        lsr_source="bybit",
    )
    onchain = OnChainSnapshot(
        sopr=1.02,
        sopr_source="glassnode",
        txcount=350_000,
        txcount_source="etherscan",
    )
    defi = DefiSnapshot(
        tvl=45_000_000_000.0,
        prev_day=44_000_000_000.0,
        prev_week=40_000_000_000.0,
        prev_month=38_000_000_000.0,
        source="defillama",
        confidence=0.8,
    )
    return MarketSnapshot(
        ticker="BTC",
        coingecko_id="bitcoin",
        price=68_000.0,
        price_source="binance",
        sopr=1.02,
        sopr_source="glassnode",
        macro={"value": {"trend": "neutral"}},
        whale_alerts=alerts,
        derivatives=derivatives,
        onchain=onchain,
        defi=defi,
        social=None,
        fused_sources=["primary", "fallback"],
        metrics={"score": 0.9},
        breaker_state={"state": "closed"},
    )


def test_snapshot_to_csv_formats_content(sample_snapshot: MarketSnapshot) -> None:
    result = _snapshot_to_csv(sample_snapshot)
    assert result is not None
    text = result.getvalue().decode("utf-8")
    assert "field,value" in text
    assert "ticker,BTC" in text
    assert "price,68000.0" in text
    assert "whale_1_amount,1000000.0" in text
    assert "whale_1_source,primary" in text


def test_snapshot_to_parquet_without_pandas_returns_none(
    sample_snapshot: MarketSnapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pandas":
            raise ModuleNotFoundError("pandas not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert _snapshot_to_parquet(sample_snapshot) is None


def test_snapshot_to_parquet_with_fake_pandas(sample_snapshot: MarketSnapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    class DummyFrame:
        def __init__(self, records):
            self.records = records

        def to_parquet(self, buf, index=False):
            buf.write(b"parquet")

    class DummyDataFrameNamespace:
        @staticmethod
        def from_records(records):
            return DummyFrame(records)

    dummy_module = types.SimpleNamespace(DataFrame=DummyDataFrameNamespace)

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pandas":
            return dummy_module
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    buffer = _snapshot_to_parquet(sample_snapshot)
    assert buffer is not None
    assert buffer.getvalue() == b"parquet"

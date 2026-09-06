import pandas as pd
import pytest

from pipeline.technical_indicators import compute_indicators, has_pandas_ta

pytestmark = pytest.mark.skipif(not has_pandas_ta(), reason="pandas-ta not installed")


def test_compute_indicators_basic():
    idx = pd.date_range("2024-01-01", periods=250, freq="H")
    df = pd.DataFrame(
        {
            "open": pd.Series(range(250), dtype=float, index=idx) + 100,
            "high": pd.Series(range(250), dtype=float, index=idx) + 101,
            "low": pd.Series(range(250), dtype=float, index=idx) + 99,
            "close": pd.Series(range(250), dtype=float, index=idx) + 100.5,
            "volume": pd.Series([1000.0] * 250, dtype=float, index=idx),
        },
        index=idx,
    )

    out = compute_indicators(
        df.copy(), indicators=["rsi", "ema", "macd", "bbands", "vwap", "ichimoku", "atr", "stoch", "adx"]
    )
    assert out.shape[0] == 250
    # Vérifie présence de quelques colonnes clés (si dispo)
    for col in ["RSI", "EMA"]:
        assert col in out.columns

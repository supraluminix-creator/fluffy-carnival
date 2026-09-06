import pandas as pd
import pytest

from pipeline.technical_indicators import compute_indicators, has_pandas_ta

pytestmark = pytest.mark.skipif(not has_pandas_ta(), reason="pandas-ta not installed")


def test_compute_indicators_cci_roc_obv():
    idx = pd.date_range("2024-01-01", periods=120, freq="H")
    df = pd.DataFrame(
        {
            "open": pd.Series(range(120), dtype=float, index=idx) + 100,
            "high": pd.Series(range(120), dtype=float, index=idx) + 101,
            "low": pd.Series(range(120), dtype=float, index=idx) + 99,
            "close": pd.Series(range(120), dtype=float, index=idx) + 100.5,
            "volume": pd.Series([1000.0] * 120, dtype=float, index=idx),
        },
        index=idx,
    )

    out = compute_indicators(df.copy(), indicators=["cci", "roc", "obv"])
    assert out.shape[0] == 120
    for col in ["CCI", "ROC", "OBV"]:
        assert col in out.columns

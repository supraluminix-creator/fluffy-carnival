import pandas as pd
import pytest

from pipeline.technical_indicators import compute_indicators, has_pandas_ta

pytestmark = pytest.mark.skipif(not has_pandas_ta(), reason="pandas-ta not installed")


def test_compute_indicators_adl_kc():
    idx = pd.date_range("2024-01-01", periods=150, freq="H")
    df = pd.DataFrame(
        {
            "open": pd.Series(range(150), dtype=float, index=idx) + 100,
            "high": pd.Series(range(150), dtype=float, index=idx) + 101,
            "low": pd.Series(range(150), dtype=float, index=idx) + 99,
            "close": pd.Series(range(150), dtype=float, index=idx) + 100.5,
            "volume": pd.Series([1000.0] * 150, dtype=float, index=idx),
        },
        index=idx,
    )

    out = compute_indicators(df.copy(), indicators=["adl", "kc"])
    assert out.shape[0] == 150
    assert "ADL" in out.columns
    # Keltner: pandas-ta nomme généralement les colonnes avec préfixe "KC" (ex: KCLe_, KCM_, KCUe_)
    assert any(c.upper().startswith("KC") for c in out.columns)

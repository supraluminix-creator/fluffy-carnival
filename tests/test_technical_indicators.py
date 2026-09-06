import importlib

import pandas as pd
import pytest


@pytest.fixture
def sample_ohlc() -> pd.DataFrame:
    # Petit jeu de données OHLC synthétique
    idx = pd.date_range("2024-01-01", periods=50, freq="H")
    df = pd.DataFrame(
        {
            "open": pd.Series(range(50), dtype=float) + 100.0,
            "high": pd.Series(range(50), dtype=float) + 101.0,
            "low": pd.Series(range(50), dtype=float) + 99.0,
            "close": pd.Series(range(50), dtype=float) + 100.5,
            "volume": pd.Series([1_000] * 50, dtype=float),
        },
        index=idx,
    )
    return df


def _skip_if_no_pandas_ta():
    try:
        importlib.import_module("pandas_ta")
    except Exception:  # pragma: no cover - chemin dépendance optionnelle
        pytest.skip("pandas-ta non installé: skip des tests d'indicateurs")


def test_has_pandas_ta_flag():
    from pipeline.technical_indicators import has_pandas_ta

    # Simple sanity: fonction retourne un bool
    assert isinstance(has_pandas_ta(), bool)


def test_compute_indicators_minimal(sample_ohlc: pd.DataFrame):
    _skip_if_no_pandas_ta()
    from pipeline.technical_indicators import compute_indicators

    df = sample_ohlc.copy()
    out = compute_indicators(df, indicators=["rsi", "ema", "macd", "bbands"])  # pas de vwap/ichimoku

    # Colonnes attendues (au moins)
    assert "RSI" in out.columns
    assert "EMA" in out.columns
    # MACD retourne plusieurs colonnes, on vérifie la présence d'au moins l'une d'elles
    assert any(col.startswith("MACD_") for col in out.columns)
    # Bollinger bands également
    assert any(col.startswith("BBL_") or col.startswith("BBM_") or col.startswith("BBU_") for col in out.columns)


def test_compute_indicators_full(sample_ohlc: pd.DataFrame):
    _skip_if_no_pandas_ta()
    from pipeline.technical_indicators import compute_indicators

    df = sample_ohlc.copy()
    out = compute_indicators(df, indicators=["rsi", "ema", "macd", "bbands", "vwap", "ichimoku"])  # full

    assert "VWAP" in out.columns
    # Ichimoku ajoute de multiples colonnes, vérif basique
    assert any("IKS_" in c or "ITS_" in c or "IKH_" in c for c in out.columns)

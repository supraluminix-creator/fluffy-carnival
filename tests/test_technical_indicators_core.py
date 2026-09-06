import pandas as pd
import pytest

import pipeline.technical_indicators as ti


class FakeTA:
    def rsi(self, close, length=14):
        return pd.Series([42] * len(close), index=close.index, name="RSI")

    def ema(self, close, length=21):
        return pd.Series([close.mean()] * len(close), index=close.index, name="EMA")

    def sma(self, close, length=20):
        return pd.Series([close.mean()] * len(close), index=close.index, name="SMA")

    def macd(self, close, fast=12, slow=26, signal=9):
        base = pd.Series(range(len(close)), index=close.index, name="MACD")
        return pd.DataFrame({"MACD": base, "MACDh": base + 1, "MACDs": base - 1})

    def bbands(self, close, length=20, std=2.0):
        base = pd.Series(range(len(close)), index=close.index)
        return pd.DataFrame({
            "BBL_20_2.0": base,
            "BBM_20_2.0": base + 1,
            "BBU_20_2.0": base + 2,
        })

    def vwap(self, high, low, close, volume):
        return pd.Series([1.0] * len(close), index=close.index, name="VWAP")

    def ichimoku(self, high, low, close):
        idx = close.index
        df = pd.DataFrame(
            {
                "ISA_9": [0.1] * len(idx),
                "ISB_26": [0.2] * len(idx),
                "ITS_9": [0.3] * len(idx),
                "IKS_26": [0.4] * len(idx),
                "ICS_26": [0.5] * len(idx),
            },
            index=idx,
        )
        return df, None

    def atr(self, high, low, close, length=14):
        return pd.Series([0.7] * len(close), index=close.index, name="ATR_14")

    def stoch(self, high, low, close, k=14, d=3, smooth_k=3):
        base = pd.Series(range(len(close)), index=close.index)
        return pd.DataFrame({"STOCHk_14": base, "STOCHd_3": base + 1})

    def adx(self, high, low, close, length=14):
        base = pd.Series(range(len(close)), index=close.index)
        return pd.DataFrame({"ADX_14": base, "DMP_14": base + 1, "DMN_14": base - 1})

    def cci(self, high, low, close, length=20):
        return pd.Series([0.2] * len(close), index=close.index, name="CCI_20")

    def roc(self, close, length=12):
        return pd.Series([0.3] * len(close), index=close.index, name="ROC_12")

    def obv(self, close, volume):
        return pd.Series([10] * len(close), index=close.index, name="OBV")

    def ad(self, high, low, close, volume):
        return pd.Series([5] * len(close), index=close.index, name="ADL")

    def kc(self, high, low, close, length=20, scalar=2.0):
        base = pd.Series(range(len(close)), index=close.index)
        return pd.DataFrame({"KCL_20": base, "KCM_20": base + 1, "KCU_20": base + 2})


@pytest.fixture
def fake_ta(monkeypatch):
    fake = FakeTA()
    monkeypatch.setattr(ti, "_ta", fake)
    return fake


def test_compute_indicators_with_fake_ta(fake_ta):
    idx = pd.date_range("2024-01-01", periods=5, freq="H")
    df = pd.DataFrame(
        {
            "close": [100, 101, 102, 103, 104],
            "high": [101, 102, 103, 104, 105],
            "low": [99, 100, 101, 102, 103],
            "volume": [10_000, 11_000, 12_000, 13_000, 14_000],
        },
        index=idx,
    )

    indicators = {
        "rsi",
        "ema",
        "sma",
        "macd",
        "bbands",
        "vwap",
        "ichimoku",
        "atr",
        "stoch",
        "adx",
        "cci",
        "roc",
        "obv",
        "adl",
        "kc",
    }

    result = ti.compute_indicators(df.copy(), indicators=indicators)
    expected_columns = {
        "RSI",
        "EMA",
        "SMA",
        "MACD",
        "MACDh",
        "MACDs",
        "BBL_20_2.0",
        "BBM_20_2.0",
        "BBU_20_2.0",
        "VWAP",
        "ISA_9",
        "ISB_26",
        "ITS_9",
        "IKS_26",
        "ICS_26",
        "ATR",
        "STOCHk_14",
        "STOCHd_3",
        "ADX_14",
        "DMP_14",
        "DMN_14",
        "CCI",
        "ROC",
        "OBV",
        "ADL",
        "KCL_20",
        "KCM_20",
        "KCU_20",
    }
    assert expected_columns.issubset(set(result.columns))
    assert len(result) == len(df)
    assert ti.has_pandas_ta() is True


def test_fetch_binance_ohlc_via_requests(monkeypatch):
    monkeypatch.setenv("RETRY_HTTP_ENABLED", "0")
    monkeypatch.setattr(ti, "is_requests_monkeypatched", lambda func: False)

    sample = [
        [1700000000000, "1", "2", "0.5", "2.5", "10", 1700000005000, "1", 42, "1", "2", "0"],
    ]

    class DummyResponse:
        def json(self):
            return sample

    captured = {}

    def fake_get(url, params, timeout):
        captured["params"] = params
        return DummyResponse()

    monkeypatch.setattr(ti.requests, "get", fake_get)

    df = ti.fetch_binance_ohlc(symbol="BTCUSDT", interval="1m", limit=1, timeout=5)
    assert df is not None
    assert list(df.columns)[:5] == ["open", "high", "low", "close", "volume"]
    assert str(df.index.name) == "timestamp"
    assert captured["params"]["symbol"] == "BTCUSDT"


def test_fetch_binance_ohlc_invalid_payload(monkeypatch):
    monkeypatch.setenv("RETRY_HTTP_ENABLED", "1")
    monkeypatch.setattr(ti, "is_requests_monkeypatched", lambda func: False)
    monkeypatch.setattr(ti, "fetch_json", lambda url, params, timeout: {"error": "bad"})

    assert ti.fetch_binance_ohlc(symbol="BTCUSDT") is None

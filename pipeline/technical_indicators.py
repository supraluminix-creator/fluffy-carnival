
import pandas as pd
import pandas_ta as ta
import requests


def fetch_binance_ohlc(symbol: str = "BTCUSDT", interval: str = "5m", limit: int = 500) -> pd.DataFrame | None:
    """
    Fetches OHLC data from Binance API.

    Parameters
    ----------
    symbol : str
        Trading pair symbol (e.g., 'BTCUSDT').
    interval : str
        Kline interval (e.g., '5m').
    limit : int
        Number of data points.

    Returns
    -------
    Optional[pd.DataFrame]
        DataFrame with OHLC data, or None if error.
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        # Correction : vérifier que la réponse est une liste
        if not isinstance(data, list):
            print(f"Erreur Binance OHLC: {data}")
            return None
        df = pd.DataFrame(data, columns=[
            "timestamp","open","high","low","close","volume",
            "close_time","qav","num_trades","taker_base_vol","taker_quote_vol","ignore"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("timestamp")
        df = df.sort_index()
        return df
    except Exception as e:
        print(f"Exception Binance OHLC: {e}")
        return None

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes RSI, MACD, Bollinger Bands, EMA, VWAP, Ichimoku.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with OHLC data.

    Returns
    -------
    pd.DataFrame
        DataFrame with indicators added.
    """
    df["RSI"] = ta.rsi(df["close"], length=14)
    macd = ta.macd(df["close"])
    df = pd.concat([df, macd], axis=1)
    bbands = ta.bbands(df["close"])
    df = pd.concat([df, bbands], axis=1)
    df["EMA"] = ta.ema(df["close"], length=21)
    df["VWAP"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
    ichimoku = ta.ichimoku(df["high"], df["low"], df["close"])  # Correction ici
    df = pd.concat([df, ichimoku[0]], axis=1)
    return df
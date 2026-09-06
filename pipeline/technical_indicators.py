from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterable
from typing import Any, cast

import pandas as pd
import requests

from pipeline.http import fetch_json
from pipeline.http_utils import is_requests_monkeypatched

# pandas-ta est une dépendance optionnelle. On évite l'import dur au chargement
# du module pour garder le core vert si le package n'est pas installé.
try:  # pragma: no cover - chemin dépendance optionnelle
    import pandas_ta as _ta  # type: ignore
except Exception:  # pragma: no cover - absence de pandas_ta
    _ta = None  # type: ignore

# Prometheus est optionnel; on tolère l'absence (prod-safe core vert)
try:  # pragma: no cover
    from prometheus_client import Counter, Histogram  # type: ignore
except Exception:  # pragma: no cover
    Histogram = None  # type: ignore
    Counter = None  # type: ignore

_INDICATORS_TIME = None
_INDICATORS_COLS = None
_ENABLE_METRICS = os.getenv("INDICATORS_METRICS", "0") == "1"
if _ENABLE_METRICS and Histogram is not None:  # pragma: no cover - instrumentation optionnelle
    _INDICATORS_TIME = Histogram(
        "indicators_compute_seconds",
        "Durée du calcul des indicateurs",
        labelnames=("indicators",),
        buckets=(0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, 5),
    )
if _ENABLE_METRICS and Counter is not None:  # pragma: no cover
    _INDICATORS_COLS = Counter(
        "indicators_columns_created_total",
        "Nombre de colonnes indicateurs ajoutées",
        labelnames=("indicator",),
    )


def has_pandas_ta() -> bool:
    """Retourne True si pandas-ta est disponible à l'exécution."""
    return _ta is not None


def _require_ta() -> Any:
    """Vérifie la présence de pandas-ta et renvoie le module sinon lève une erreur explicite."""
    if _ta is None:  # pragma: no cover - exercé uniquement si non installé
        raise ImportError(
            "pandas-ta n'est pas installé. Installez-le pour calculer les indicateurs: pip install pandas-ta"
        )
    return _ta


def fetch_binance_ohlc(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    limit: int = 500,
    *,
    timeout: float = 10.0,
) -> pd.DataFrame | None:
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
    params: dict[str, str | int] = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        # Utilise la façade si retry global activé et si requests.get n'est pas monkeypatché.
        # Si requests.get est patché (module != "requests"), on retombe sur le chemin legacy
        # pour préserver les tests qui injectent des payloads simplifiés.
        is_monkeypatched = is_requests_monkeypatched(getattr(requests, "get", None))

        retry_enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
        if retry_enabled and not is_monkeypatched:
            data = fetch_json(url, params=params, timeout=timeout)
        else:
            resp = requests.get(url, params=params, timeout=timeout)
            data = resp.json()
        # Correction : vérifier que la réponse est une liste
        if not isinstance(data, list):
            print(f"Erreur Binance OHLC: {data}")
            return None
        df = pd.DataFrame(
            data,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "qav",
                "num_trades",
                "taker_base_vol",
                "taker_quote_vol",
                "ignore",
            ],
        )
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("timestamp")
        df = df.sort_index()
        return df
    except Exception as e:
        print(f"Exception Binance OHLC: {e}")
        return None


def get_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Calcule le RSI à partir d'une série de clôture."""
    ta = _require_ta()
    return cast(pd.Series, ta.rsi(close, length=length))


def get_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Calcule le MACD et renvoie un DataFrame des composantes (macd, signal, histogram)."""
    ta = _require_ta()
    return cast(pd.DataFrame, ta.macd(close, fast=fast, slow=slow, signal=signal))


def get_bbands(close: pd.Series, length: int = 20, std: float = 2.0) -> pd.DataFrame:
    """Calcule les bandes de Bollinger (haut, milieu, bas)."""
    ta = _require_ta()
    return cast(pd.DataFrame, ta.bbands(close, length=length, std=std))


def get_ema(close: pd.Series, length: int = 21) -> pd.Series:
    """Calcule l'EMA."""
    ta = _require_ta()
    return cast(pd.Series, ta.ema(close, length=length))


def get_sma(close: pd.Series, length: int = 20) -> pd.Series:
    """Calcule la SMA."""
    ta = _require_ta()
    return cast(pd.Series, ta.sma(close, length=length))


def get_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Calcule le VWAP. Requiert high/low/close/volume."""
    ta = _require_ta()
    return cast(pd.Series, ta.vwap(high, low, close, volume))


def get_cci(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 20) -> pd.Series:
    """Calcule le CCI (Commodity Channel Index)."""
    ta = _require_ta()
    cci = cast(pd.Series, ta.cci(high, low, close, length=length))
    cci.name = "CCI"
    return cci


def get_roc(close: pd.Series, length: int = 12) -> pd.Series:
    """Calcule le ROC (Rate of Change)."""
    ta = _require_ta()
    roc = cast(pd.Series, ta.roc(close, length=length))
    roc.name = "ROC"
    return roc


def get_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Calcule l'OBV (On Balance Volume)."""
    ta = _require_ta()
    obv = cast(pd.Series, ta.obv(close, volume))
    obv.name = "OBV"
    return obv


def get_adl(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Calcule l'ADL (Accumulation/Distribution Line) via pandas-ta.ad puis renomme en ADL."""
    ta = _require_ta()
    ad = cast(pd.Series, ta.ad(high, low, close, volume))
    ad.name = "ADL"
    return ad


def get_kc(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 20, scalar: float = 2.0) -> pd.DataFrame:
    """Calcule les Keltner Channels (KC)."""
    ta = _require_ta()
    # pandas-ta.kc renvoie un DataFrame avec bandes inf/mid/sup
    return cast(pd.DataFrame, ta.kc(high, low, close, length=length, scalar=scalar))


def get_ichimoku(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.DataFrame:
    """Calcule Ichimoku. Retourne le premier élément (DataFrame principal) comme pandas-ta."""
    ta = _require_ta()
    out = ta.ichimoku(high, low, close)
    # pandas-ta.ichimoku retourne un tuple (df, span)
    main = out[0] if isinstance(out, tuple | list) else out
    # Si données insuffisantes, pandas-ta peut retourner None; on crée une trame vide avec colonnes attendues
    if main is None or not isinstance(main, pd.DataFrame):
        cols = ["ISA_9", "ISB_26", "ITS_9", "IKS_26", "ICS_26"]
        return pd.DataFrame(index=close.index, columns=cols, dtype=float)
    return cast(pd.DataFrame, main)


def get_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Calcule l'Average True Range (ATR)."""
    ta = _require_ta()
    # pandas-ta renvoie une Series nommée "ATR_{length}"; on normalise en colonne "ATR".
    atr = cast(pd.Series, ta.atr(high, low, close, length=length))
    # On renomme pour une colonne plus stable coté export/analyses
    atr.name = "ATR"
    return atr


def get_stoch(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k: int = 14,
    d: int = 3,
    smooth_k: int = 3,
) -> pd.DataFrame:
    """Calcule le Stochastique (%K, %D)."""
    ta = _require_ta()
    return cast(pd.DataFrame, ta.stoch(high, low, close, k=k, d=d, smooth_k=smooth_k))


def get_adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.DataFrame:
    """Calcule l'ADX (+DMI/-DMI inclus) et renvoie un DataFrame."""
    ta = _require_ta()
    return cast(pd.DataFrame, ta.adx(high, low, close, length=length))


def compute_indicators(
    df: pd.DataFrame,
    indicators: Iterable[str] | None = None,
    rsi_length: int = 14,
    ema_length: int = 21,
    bb_length: int = 20,
    bb_std: float = 2.0,
    atr_length: int = 14,
    stoch_k: int = 14,
    stoch_d: int = 3,
    stoch_smooth_k: int = 3,
    adx_length: int = 14,
    cci_length: int = 20,
    roc_length: int = 12,
    kc_length: int = 20,
    kc_scalar: float = 2.0,
) -> pd.DataFrame:
    """
    Ajoute les indicateurs demandés au DataFrame fourni.

    - Tolère les colonnes manquantes: calcule uniquement ce qui est possible.
    - Nécessite pandas-ta installé; sinon ImportError clair.

    Paramètres
    ----------
    df : pd.DataFrame
        Doit contenir au minimum la colonne 'close' pour RSI/MACD/EMA/SMA/BB.
        VWAP et Ichimoku requièrent aussi 'high' et 'low' (+ 'volume' pour VWAP).
    indicators : Iterable[str] | None
        Ex: {"rsi","macd","bbands","ema","sma","vwap","ichimoku"}.
        Si None, calcule un set par défaut {rsi, macd, bbands, ema}.
    """
    # Vérifie la présence de pandas-ta à l'appel
    _ = _require_ta()

    want = set(indicators or ("rsi", "macd", "bbands", "ema"))

    # Instrumentation (facultative)
    _timer = time.perf_counter()
    _labels = ",".join(sorted(want))

    if "rsi" in want and "RSI" not in df.columns and "close" in df.columns:
        df["RSI"] = get_rsi(df["close"], length=rsi_length)
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="rsi").inc()

    if "ema" in want and "EMA" not in df.columns and "close" in df.columns:
        df["EMA"] = get_ema(df["close"], length=ema_length)
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="ema").inc()

    if "sma" in want and "SMA" not in df.columns and "close" in df.columns:
        df["SMA"] = get_sma(df["close"])  # longueur par défaut
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="sma").inc()

    if "macd" in want and "close" in df.columns:
        macd_df = get_macd(df["close"])  # colonnes nommées par pandas-ta
        df = pd.concat([df, macd_df], axis=1)
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="macd").inc(len([c for c in macd_df.columns]))

    if "bbands" in want and "close" in df.columns:
        bb_df = get_bbands(df["close"], length=bb_length, std=bb_std)
        df = pd.concat([df, bb_df], axis=1)
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="bbands").inc(len([c for c in bb_df.columns]))

    if "vwap" in want and all(c in df.columns for c in ("high", "low", "close", "volume")):
        df["VWAP"] = get_vwap(df["high"], df["low"], df["close"], df["volume"])
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="vwap").inc()

    if "ichimoku" in want and all(c in df.columns for c in ("high", "low", "close")):
        ichi_df = get_ichimoku(df["high"], df["low"], df["close"])
        df = pd.concat([df, ichi_df], axis=1)
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="ichimoku").inc(len([c for c in ichi_df.columns]))

    if "atr" in want and all(c in df.columns for c in ("high", "low", "close")):
        df["ATR"] = get_atr(df["high"], df["low"], df["close"], length=atr_length)
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="atr").inc()

    if "stoch" in want and all(c in df.columns for c in ("high", "low", "close")):
        stoch_df = get_stoch(df["high"], df["low"], df["close"], k=stoch_k, d=stoch_d, smooth_k=stoch_smooth_k)
        df = pd.concat([df, stoch_df], axis=1)
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="stoch").inc(len([c for c in stoch_df.columns]))

    if "adx" in want and all(c in df.columns for c in ("high", "low", "close")):
        adx_df = get_adx(df["high"], df["low"], df["close"], length=adx_length)
        df = pd.concat([df, adx_df], axis=1)
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="adx").inc(len([c for c in adx_df.columns]))

    if "cci" in want and all(c in df.columns for c in ("high", "low", "close")):
        df["CCI"] = get_cci(df["high"], df["low"], df["close"], length=cci_length)
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="cci").inc()

    if "roc" in want and "close" in df.columns:
        df["ROC"] = get_roc(df["close"], length=roc_length)
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="roc").inc()

    if "obv" in want and all(c in df.columns for c in ("close", "volume")):
        df["OBV"] = get_obv(df["close"], df["volume"])
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="obv").inc()

    if "adl" in want and all(c in df.columns for c in ("high", "low", "close", "volume")):
        df["ADL"] = get_adl(df["high"], df["low"], df["close"], df["volume"])
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="adl").inc()

    if "kc" in want and all(c in df.columns for c in ("high", "low", "close")):
        kc_df = get_kc(df["high"], df["low"], df["close"], length=kc_length, scalar=kc_scalar)
        df = pd.concat([df, kc_df], axis=1)
        if _INDICATORS_COLS is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                _INDICATORS_COLS.labels(indicator="kc").inc(len([c for c in kc_df.columns]))

    # Fin instrumentation
    if _INDICATORS_TIME is not None:  # pragma: no cover
        with contextlib.suppress(Exception):
            _INDICATORS_TIME.labels(indicators=_labels).observe(max(0.0, time.perf_counter() - _timer))
    return df

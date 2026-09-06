"""Dataset loader pour analyses AI.

Objectif MVP:
- Charger le dernier export CSV (exports/latest_export.csv)
- Fournir des helpers pour filtrer par metric, symbol, fenêtre
- Retourner des DataFrames prêts pour features/LLM
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

DEFAULT_EXPORT = Path("exports/latest_export.csv")


def load_latest_export(path: str | Path = DEFAULT_EXPORT) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Export introuvable: {path}")
    df = pd.read_csv(path)
    # Normalisations légères
    if "timestamp" in df.columns:
        # try parse; ne plante pas si mixte
        df["timestamp_parsed"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df


def filter_metrics(df: pd.DataFrame, metrics: Iterable[str]) -> pd.DataFrame:
    mset = {m.lower() for m in metrics}
    if "metric_name" not in df.columns:
        return df.iloc[0:0]
    return df[df["metric_name"].str.lower().isin(mset)].copy()


def filter_symbol(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if "symbol" not in df.columns:
        return df.iloc[0:0]
    return df[df["symbol"].str.upper() == symbol.upper()].copy()


def last_n(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.tail(n).copy()

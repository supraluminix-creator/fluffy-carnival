from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from pipeline.technical_indicators import compute_indicators, fetch_binance_ohlc, has_pandas_ta


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _synthetic_ohlc(periods: int = 300, freq: str = "1h") -> pd.DataFrame:
    idx = pd.date_range(datetime.now(UTC) - timedelta(hours=periods), periods=periods, freq=freq.lower())
    # Petite tendance + bruit
    base = pd.Series(range(periods), dtype=float, index=idx)
    close = 100 + base * 0.1
    high = close + 1.0
    low = close - 1.0
    open_ = close.shift(1).fillna(close.iloc[0])
    vol = pd.Series(1000.0, index=idx)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)
    df.index.name = "timestamp"
    return df


def generate_indicators_csv(
    *,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    limit: int = 300,
    source: str = "synthetic",
    indicators: Iterable[str] = ("rsi", "ema", "macd", "bbands"),
    out_dir: str = "exports/indicators",
    filename: str | None = None,
    out_format: str = "csv",
    binance_timeout: float = 10.0,
    binance_retries: int = 2,
) -> dict:
    """Génère un CSV d'indicateurs et retourne le manifest (écrit aussi en JSONL)."""
    if not has_pandas_ta():
        raise RuntimeError("pandas-ta non installé. Installez-le pour calculer les indicateurs: pip install pandas-ta")

    indicators_list: list[str] = [s.strip() for s in indicators if str(s).strip()]

    if source == "binance":
        df = None
        last_err: Exception | None = None
        for _ in range(max(1, binance_retries)):
            try:
                df = fetch_binance_ohlc(symbol=symbol, interval=interval, limit=limit, timeout=binance_timeout)
                if df is not None:
                    break
            except Exception as e:  # pragma: no cover - robustesse réseau
                last_err = e
        if df is None:
            if last_err:
                print(f"Echec fetch binance (will fallback): {last_err}")
            print("Echec fetch binance; bascule sur source synthétique")
            df = _synthetic_ohlc(periods=limit, freq=interval)
    else:
        df = _synthetic_ohlc(periods=limit, freq=interval)

    df_ind = compute_indicators(df.copy(), indicators=indicators_list)

    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    base_name = filename or f"ind_{symbol}_{interval}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if out_format not in {"csv", "parquet"}:
        raise ValueError("out_format must be 'csv' or 'parquet'")
    out_path: Path
    if out_format == "csv":
        out_path = out_dir_p / f"{base_name}.csv"
        # Export large (OHLC + indicateurs) en colonnes larges
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", *df_ind.columns])
            for ts, row in df_ind.iterrows():
                # Utilise str(ts) pour compat typage (pandas.Timestamp -> string ISO-like)
                writer.writerow([str(ts), *row.tolist()])
    else:
        out_path = out_dir_p / f"{base_name}.parquet"
        df_out = df_ind.reset_index().rename(columns={"index": "timestamp"})
        try:
            df_out.to_parquet(out_path, index=False)
        except Exception as e:  # pragma: no cover - pyarrow/fastparquet absent
            raise RuntimeError(f"Parquet export failed: {e}") from e

    digest = _sha256_file(out_path)

    mani = {
        "created_at": datetime.now(UTC).isoformat(),
        "symbol": symbol,
        "interval": interval,
        "indicators": indicators_list,
        "path": out_path.as_posix(),
        "row_count": int(df_ind.shape[0]),
        "columns": ["timestamp", *df_ind.columns.tolist()],
        "sha256": digest,
        "source": source,
        "format": out_format,
    }
    mani_path = out_dir_p / "indicators_manifest.jsonl"
    with mani_path.open("a", encoding="utf-8") as mf:
        mf.write(json.dumps(mani) + "\n")

    return {"status": "OK", **mani}


def main() -> int:
    p = argparse.ArgumentParser(
        description="Génère un fichier d'indicateurs techniques à partir d'un OHLC (CSV/Parquet)"
    )
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--interval", default="1h")
    p.add_argument("--limit", type=int, default=300)
    p.add_argument("--source", choices=["binance", "synthetic"], default="synthetic")
    p.add_argument("--indicators", default="rsi,ema,macd,bbands")
    p.add_argument("--out-dir", default="exports/indicators")
    p.add_argument(
        "--filename", default=None, help="Nom de fichier sans extension; par défaut auto basé sur symbol/interval"
    )
    p.add_argument("--out-format", choices=["csv", "parquet"], default="csv")
    p.add_argument("--binance-timeout", type=float, default=10.0)
    p.add_argument("--binance-retries", type=int, default=2)
    args = p.parse_args()

    if not has_pandas_ta():
        print("pandas-ta non installé. Installez-le pour calculer les indicateurs: pip install pandas-ta")
        return 1

    indicators: list[str] = [s.strip() for s in args.indicators.split(",") if s.strip()]

    res = generate_indicators_csv(
        symbol=args.symbol,
        interval=args.interval,
        limit=args.limit,
        source=args.source,
        indicators=indicators,
        out_dir=args.out_dir,
        filename=args.filename,
        out_format=args.out_format,
        binance_timeout=args.binance_timeout,
        binance_retries=args.binance_retries,
    )

    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

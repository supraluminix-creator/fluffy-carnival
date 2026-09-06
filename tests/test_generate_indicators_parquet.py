from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.technical_indicators import has_pandas_ta


def _has_parquet() -> bool:
    try:
        import pyarrow as _  # type: ignore  # noqa: F401

        return True
    except Exception:
        try:
            import fastparquet as _  # type: ignore  # noqa: F401

            return True
        except Exception:
            return False


pytestmark = pytest.mark.skipif(not has_pandas_ta() or not _has_parquet(), reason="pandas-ta or parquet engine missing")


def test_generate_indicators_parquet(tmp_path: Path):
    from tools.generate_indicators_csv import generate_indicators_csv

    out_dir = tmp_path / "ind"
    res = generate_indicators_csv(
        symbol="BTCUSDT",
        interval="1h",
        limit=100,
        source="synthetic",
        indicators=("rsi", "ema", "macd", "bbands"),
        out_dir=str(out_dir),
        filename="unit_test_indicators_parquet",
        out_format="parquet",
    )
    assert res.get("status") == "OK"
    path = Path(res["path"]).resolve()
    assert path.exists() and path.suffix == ".parquet"

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd  # noqa: F401  # utilisé implicitement via pandas-ta
import pytest

from pipeline.technical_indicators import has_pandas_ta

pytestmark = pytest.mark.skipif(not has_pandas_ta(), reason="pandas-ta not installed")


def test_generate_indicators_csv_synthetic(tmp_path: Path):
    from tools.generate_indicators_csv import generate_indicators_csv

    out_dir = tmp_path / "ind"
    res = generate_indicators_csv(
        symbol="BTCUSDT",
        interval="1h",
        limit=120,
        source="synthetic",
        indicators=("rsi", "ema", "macd", "bbands", "atr", "stoch", "adx"),
        out_dir=str(out_dir),
        filename="unit_test_indicators",
    )

    assert res.get("status") == "OK"
    csv_path = Path(res["path"]).resolve()
    assert csv_path.exists(), "CSV non généré"

    # Manifest JSONL
    mani_path = out_dir / "indicators_manifest.jsonl"
    assert mani_path.exists(), "Manifest non créé"
    last = None
    with mani_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            last = json.loads(line)
    assert last is not None
    assert last.get("path") == res["path"]
    assert int(last.get("row_count", 0)) == 120

"""Minimal CLI to run core collectors and export results.

Usage (PowerShell):
  .\\.venv\\Scripts\\python.exe cli_core.py --symbol bitcoin
  .\\.venv\\Scripts\\python.exe cli_core.py --mock
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from pipeline.export_utils import export_latest_and_timestamped
from pipeline.collectors.market import fetch_macro
from pipeline.collectors.sentiment import fetch_fear_greed
from pipeline.collectors.derivatives import (
    fetch_bybit_long_short_ratio,
    fetch_bybit_oi,
)


EXAMPLES_DIR = Path("examples")


def _mock_records(symbol: str) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": None,
            "asset": symbol,
            "symbol": symbol,
            "metric_name": "macro_price_usd",
            "value": {"price": 50000.0},
            "source": "mock",
            "confidence_score": 1.0,
        },
        {
            "timestamp": None,
            "asset": "BTC",
            "symbol": "BTC",
            "metric_name": "fear_greed",
            "value": {"value": 64},
            "source": "mock",
            "confidence_score": 0.9,
        },
    ]


async def _real_records(symbol: str) -> list[dict[str, Any]]:
    cmc_api_key = os.getenv("CMC_API_KEY") or os.getenv("COINMARKETCAP_API_KEY") or None
    results: list[dict[str, Any]] = []
    try:
        m = fetch_macro(symbol, cmc_api_key=cmc_api_key)
        if isinstance(m, dict) and m:
            results.append(m)  # type: ignore[arg-type]
    except Exception as e:
        print(f"macro error: {e}")
    try:
        fg = await fetch_fear_greed()
        if isinstance(fg, dict) and fg:
            results.append(fg)  # type: ignore[arg-type]
    except Exception as e:
        print(f"fear_greed error: {e}")
    try:
        oi = await fetch_bybit_oi("BTCUSDT")
        if isinstance(oi, dict) and oi:
            results.append(oi)  # type: ignore[arg-type]
        lsr = await fetch_bybit_long_short_ratio("BTCUSDT")
        if isinstance(lsr, dict) and lsr:
            results.append(lsr)  # type: ignore[arg-type]
    except Exception as e:
        print(f"derivatives error: {e}")
    return results


def write_examples(rows: list[dict[str, Any]]) -> None:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    # Save JSON
    (EXAMPLES_DIR / "sample_export.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="bitcoin")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--export-dir", default="exports")
    args = ap.parse_args()

    if args.mock:
        rows = _mock_records(args.symbol)
    else:
        rows = asyncio.run(_real_records(args.symbol))
    write_examples(rows)
    latest, ts = export_latest_and_timestamped(rows, export_dir=args.export_dir)
    print("Exported:", latest, ts)


if __name__ == "__main__":
    main()

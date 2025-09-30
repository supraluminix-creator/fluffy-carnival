"""Minimal prod-safe CLI to run core collectors and export outputs.

Examples (PowerShell):
  # Real public-only run (no paid keys), exports CSVs under exports/
  python cli_core.py run --symbol bitcoin --public-only

  # Mock run (no network), generates example outputs in exports/ and examples/
  python cli_core.py run --mock
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from pipeline.export_utils import export_latest_and_timestamped


EXAMPLES_DIR = Path("examples")


async def collect_public(symbol: str = "bitcoin") -> List[Dict[str, Any]]:
    """Collect a minimal set of public metrics without paid keys."""
    results: List[Dict[str, Any]] = []
    try:
        from pipeline.collectors.market import fetch_macro
        res = await fetch_macro(symbol, cmc_api_key=None)
        if isinstance(res, dict) and res:
            results.append(res)
    except Exception as e:
        print("collect_public: market.fetch_macro failed:", e)
    try:
        from pipeline.collectors.sentiment import fetch_fear_greed
        res = await fetch_fear_greed()
        if isinstance(res, dict) and res:
            results.append(res)
    except Exception as e:
        print("collect_public: sentiment.fetch_fear_greed failed:", e)
    return results


def make_mock_records(symbol: str = "bitcoin") -> List[Dict[str, Any]]:
    return [
        {
            "timestamp": None,
            "asset": symbol,
            "symbol": "BTC",
            "chain": "-",
            "metric_name": "macro_price_usd",
            "value": {"price": 64000.0},
            "source": "mock",
            "confidence_score": 1.0,
        },
        {
            "timestamp": None,
            "asset": "BTC",
            "symbol": "BTC",
            "chain": "-",
            "metric_name": "fear_greed",
            "value": {"value": 56},
            "source": "mock",
            "confidence_score": 1.0,
        },
    ]


def write_examples(rows: List[Dict[str, Any]]) -> None:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    (EXAMPLES_DIR / "sample_export.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def main_async(args: argparse.Namespace) -> int:
    if args.command == "run":
        rows: List[Dict[str, Any]]
        if args.mock:
            rows = make_mock_records(args.symbol)
        else:
            rows = await collect_public(symbol=args.symbol)
        write_examples(rows)
        export_dir = os.getenv("EXPORT_DIR", "exports")
        latest, ts = export_latest_and_timestamped(rows, export_dir=export_dir, run_id=os.getenv("RUN_ID"))
        summary = {
            "records": len(rows),
            "latest": latest,
            "timestamped": ts,
        }
        print(json.dumps(summary, indent=2))
        return 0
    return 1


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cli_core", description="Prod-safe core CLI for collectors")
    sub = ap.add_subparsers(dest="command")
    p_run = sub.add_parser("run", help="Run minimal collectors and export outputs")
    p_run.add_argument("--symbol", default="bitcoin")
    p_run.add_argument("--mock", action="store_true", help="Run in mock mode (no network)")
    p_run.add_argument("--public-only", action="store_true", help="Alias of real run with public endpoints only")
    args = ap.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

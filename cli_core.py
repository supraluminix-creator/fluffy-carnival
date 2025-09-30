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
from typing import Any

from pipeline.export_utils import export_latest_and_timestamped

EXAMPLES_DIR = Path("examples")


async def collect_public(symbol: str = "bitcoin", include_derivatives: bool = False) -> list[dict[str, Any]]:
    """Collect a minimal set of public metrics without paid keys.

    If include_derivatives is True, also attempts Bybit OI/LSR (public endpoints).
    """
    results: list[dict[str, Any]] = []
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
    if include_derivatives:
        try:
            from pipeline.collectors.derivatives import (
                fetch_bybit_long_short_ratio,
                fetch_bybit_oi,
            )
            oi = await fetch_bybit_oi("BTCUSDT")
            if isinstance(oi, dict) and oi:
                results.append(oi)
            lsr = await fetch_bybit_long_short_ratio("BTCUSDT")
            if isinstance(lsr, dict) and lsr:
                results.append(lsr)
        except Exception as e:
            print("collect_public: derivatives failed:", e)
    return results


def make_mock_records(symbol: str = "bitcoin") -> list[dict[str, Any]]:
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


def write_examples(rows: list[dict[str, Any]]) -> None:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    (EXAMPLES_DIR / "sample_export.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def main_async(args: argparse.Namespace) -> int:
    if args.command == "run":
        rows: list[dict[str, Any]]
        if args.mock:
            rows = make_mock_records(args.symbol)
        else:
            rows = await collect_public(symbol=args.symbol, include_derivatives=args.include_derivatives)
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
    if args.command == "validate":
        info = {
            "EXPORT_DIR": os.getenv("EXPORT_DIR", "exports"),
            "ENABLE_MVRV_COLLECTOR": os.getenv("ENABLE_MVRV_COLLECTOR", "0"),
            "ENABLE_MACRO_INDICES": os.getenv("ENABLE_MACRO_INDICES", "0"),
            "HTTP_THROTTLE_PER_MIN_DEFAULT": os.getenv("HTTP_THROTTLE_PER_MIN_DEFAULT", "0"),
        }
        # Check presence of optional API keys (masked)
        def mask(v: str | None) -> str:
            if not v:
                return ""
            return (v[:3] + "…" + v[-2:]) if len(v) > 6 else "***"
        keys = {
            "CMC_API_KEY": mask(os.getenv("CMC_API_KEY")),
            "COINMARKETCAP_API_KEY": mask(os.getenv("COINMARKETCAP_API_KEY")),
            "ETHERSCAN_API_KEY": mask(os.getenv("ETHERSCAN_API_KEY")),
            "BGEOMETRICS_API_KEY": mask(os.getenv("BGEOMETRICS_API_KEY")),
        }
        print(json.dumps({"env": info, "keys": keys, "collectors": ["macro", "fear_greed", "bybit_oi", "bybit_lsr"]}, indent=2))
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cli_core", description="Prod-safe core CLI for collectors")
    sub = ap.add_subparsers(dest="command")
    p_run = sub.add_parser("run", help="Run minimal collectors and export outputs")
    p_run.add_argument("--symbol", default="bitcoin")
    p_run.add_argument("--mock", action="store_true", help="Run in mock mode (no network)")
    p_run.add_argument("--public-only", action="store_true", help="Alias of real run with public endpoints only")
    p_run.add_argument(
        "--include-derivatives",
        action="store_true",
        help="Include public derivatives metrics (Bybit OI/LSR) in non-mock runs",
    )
    # validate
    _p_val = sub.add_parser("validate", help="Check environment and list available collectors")
    args = ap.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

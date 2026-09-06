#!/usr/bin/env python3
"""Compute probabilistic market scores for one or more symbols."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from pipeline.scoring.probabilistic import score_asset


def _parse_mapping(values: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            continue
        key, val = raw.split("=", 1)
        key = key.strip().upper()
        val = val.strip()
        if key and val:
            mapping[key] = val
    return mapping


def _load_whale_events(path: str | None) -> list[dict[str, Any]] | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.exists():
        raise FileNotFoundError(f"Whale events file not found: {path}")
    data = json.loads(candidate.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [event for event in data if isinstance(event, dict)]
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+", help="Asset symbols to score (ex: BTC ETH)")
    parser.add_argument(
        "--coinalyze-market",
        action="append",
        default=[],
        help="Map symbol to Coinalyze market (format: SYMBOL=MARKET)",
    )
    parser.add_argument(
        "--coindesk-symbol",
        action="append",
        default=[],
        help="Map symbol to Coindesk orderbook symbol (format: SYMBOL=SYMBOL_USD)",
    )
    parser.add_argument(
        "--whale-events",
        default=None,
        help="Path to JSON file with precomputed whale events",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to write the resulting JSON report",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days for CoinGecko historical window (default: %(default)s)",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> list[dict[str, Any]]:
    coinalyze_map = _parse_mapping(args.coinalyze_market)
    coindesk_map = _parse_mapping(args.coindesk_symbol)
    coinalyze_key = os.getenv("COINALYZE_API_KEY")
    coindesk_key = os.getenv("COINDESK_API_KEY") or os.getenv("CCDATA_API_KEY")
    whale_events = _load_whale_events(args.whale_events)

    reports: list[dict[str, Any]] = []
    for symbol in args.symbols:
        norm = symbol.upper()
        report = await score_asset(
            norm,
            coinalyze_market=coinalyze_map.get(norm),
            coinalyze_api_key=coinalyze_key,
            coindesk_symbol=coindesk_map.get(norm),
            coindesk_api_key=coindesk_key,
            whale_events=whale_events,
            days=args.days,
        )
        payload = {
            "symbol": report.symbol,
            "coingecko_id": report.coingecko_id,
            "score": report.score,
            "strategy": report.strategy,
            "components": {
                "volatility_annualized": report.components.volatility_annualized,
                "volume_funding_ratio": report.components.volume_funding_ratio,
                "funding_rate": report.components.funding_rate,
                "orderbook_imbalance": report.components.orderbook_imbalance,
                "whale_pressure": report.components.whale_pressure,
            },
            "context": report.context,
        }
        reports.append(payload)
    return reports


def main() -> int:
    args = parse_args()
    reports = asyncio.run(_run(args))
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(f"Wrote probabilistic scoring report to {out_path}")
    else:
        print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

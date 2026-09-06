#!/usr/bin/env python3
"""Refresh the cross-exchange symbol registry JSON file."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pipeline.assets import COINGECKO_IDS
from pipeline.mappings import refresh_symbol_registry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="data/mappings/symbol_registry.json",
        help="Destination path for the registry JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "--preferred-id",
        action="append",
        default=[],
        help="Extra CoinGecko ids to treat as preferred when resolving conflicts",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> Path:
    preferred = set(COINGECKO_IDS.values()) | set(args.preferred_id or [])
    path = await refresh_symbol_registry(output_path=args.output, preferred_ids=preferred)
    return path


def main() -> int:
    args = parse_args()
    path = asyncio.run(_run(args))
    print(f"Symbol registry written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

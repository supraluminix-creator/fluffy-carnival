"""Utility to refresh or inspect the latest ETH whale balances snapshot.

The script either triggers a fresh collection (default) or prints the
most recent snapshot stored on disk. Usage examples:

    python -m scripts.dump_whale_balances
    python -m scripts.dump_whale_balances --load-only --json
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from numbers import Real
from typing import Any

import structlog

from pipeline.collectors import whales

log = structlog.get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect ETH whale balance snapshots")
    parser.add_argument(
        "--load-only",
        action="store_true",
        help="Do not call Etherscan; load the latest snapshot written to disk",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON payload instead of a formatted table",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Limit the number of addresses displayed in the table (default: 10)",
    )
    return parser.parse_args()


def _format_timestamp(ts: int | float | None) -> str:
    if ts is None:
        return "unknown"
    try:
        return dt.datetime.fromtimestamp(float(ts), tz=dt.UTC).isoformat()
    except Exception:  # pragma: no cover - defensive formatting
        return "invalid"


def _print_table(record: dict[str, Any], top: int) -> None:
    addresses = record.get("addresses")
    if not isinstance(addresses, list) or not addresses:
        print("No whale addresses in snapshot")
        return
    total_eth_raw = record.get("total_eth")
    total_eth_float = 0.0
    if isinstance(total_eth_raw, Real):
        total_eth_float = float(total_eth_raw)
    elif isinstance(total_eth_raw, str):
        try:
            total_eth_float = float(total_eth_raw)
        except ValueError:
            total_eth_float = 0.0
    entries: list[tuple[str, float]] = []
    for item in addresses:
        if not isinstance(item, dict):
            continue
        addr = item.get("address")
        bal = item.get("balance_eth")
        if not isinstance(addr, str) or not isinstance(bal, Real):
            continue
        entries.append((addr, float(bal)))
    if not entries:
        print("No valid whale entries to display")
        return
    entries.sort(key=lambda r: r[1], reverse=True)
    if top > 0:
        entries = entries[:top]
    header = f"{'Address':<44} {'Balance ETH':>14} {'Share':>8}"
    print(header)
    print("-" * len(header))
    for addr, balance in entries:
        share = (balance / total_eth_float * 100.0) if total_eth_float > 0 else 0.0
        print(f"{addr:<44} {balance:>14.4f} {share:>7.2f}%")


async def _refresh_snapshot(load_only: bool) -> tuple[dict[str, Any] | None, bool]:
    if load_only:
        return whales.load_latest_snapshot(), False
    record = await whales.fetch_eth_whale_balances()
    if record:
        return record, True
    fallback = whales.load_latest_snapshot()
    if fallback:
        log.warning("whale_balances_refresh_failed_using_cache")
    return fallback, False


async def _async_main(args: argparse.Namespace) -> int:
    record, fresh = await _refresh_snapshot(args.load_only)
    if not record:
        log.error("whale_balances_snapshot_unavailable")
        if args.load_only:
            print(
                "No whale balance snapshot found. Run this script without --load-only after "
                "configuring the Etherscan collector (ENABLE_WHALE_BALANCES=1, ETHERSCAN_*) to "
                "generate the initial snapshot.",
                file=sys.stderr,
            )
        else:
            print(
                "Failed to refresh whale balances. Check your Etherscan configuration (API key, "
                "address list, ETHERSCAN_ENABLED) and network connectivity.",
                file=sys.stderr,
            )
        return 1
    metadata = {
        "source": record.get("source", "unknown"),
        "generated_at": record.get("generated_at"),
        "fresh": fresh,
        "address_count": len(record.get("addresses") or []),
        "total_eth": record.get("total_eth"),
    }
    if args.json:
        payload = {
            "metadata": metadata,
            "record": record,
        }
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0
    print(f"Source       : {metadata['source']}")
    print(f"Generated at : {_format_timestamp(metadata['generated_at'])}")
    print(f"Address count: {metadata['address_count']}")
    try:
        total_eth = float(metadata["total_eth"])
        print(f"Total ETH    : {total_eth:.4f}")
    except Exception:
        print("Total ETH    : unknown")
    print("Fresh fetch  : {}".format("yes" if fresh else "no"))
    print()
    _print_table(record, args.top)
    return 0


def main() -> None:
    args = _parse_args()
    try:
        exit_code = asyncio.run(_async_main(args))
    except KeyboardInterrupt:  # pragma: no cover - CLI convenience
        print("Interrupted", file=sys.stderr)
        exit_code = 130
    sys.exit(exit_code)


if __name__ == "__main__":  # pragma: no cover
    main()

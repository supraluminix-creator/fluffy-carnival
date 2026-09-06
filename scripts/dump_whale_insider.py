"""Utility to refresh and inspect the combined insider whale snapshot.

The snapshot merges Hyperliquid derivative positions and on-chain ETH balances
for the configured watchlists.

Examples:
    python -m scripts.dump_whale_insider
    python -m scripts.dump_whale_insider --load-only --json
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

from pipeline.collectors import whale_insider

log = structlog.get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect insider whale snapshot (Hyperliquid + ETH)")
    parser.add_argument(
        "--load-only",
        action="store_true",
        help="Do not call remote APIs; load the latest snapshot from disk",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw JSON payload instead of a formatted summary",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of Hyperliquid positions to display (default: 10)",
    )
    return parser.parse_args()


def _format_timestamp(ts: int | float | None) -> str:
    if ts is None:
        return "unknown"
    try:
        return dt.datetime.fromtimestamp(float(ts), tz=dt.UTC).isoformat()
    except Exception:  # pragma: no cover - defensive formatting
        return "invalid"


def _extract_positions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for record in records:
        if record.get("metric_name") != "hl_position_notional_usd":
            continue
        try:
            notional = float(record.get("value", 0.0))
        except Exception:
            notional = 0.0
        metadata = record.get("metadata") or {}
        positions.append(
            {
                "trader": record.get("trader") or "-",
                "symbol": record.get("symbol") or "-",
                "side": str(metadata.get("side") or "-"),
                "notional": notional,
                "leverage": metadata.get("leverage"),
            }
        )
    positions.sort(key=lambda item: item["notional"], reverse=True)
    return positions


def _print_summary(snapshot: dict[str, Any], *, limit: int) -> None:
    meta = snapshot.get("meta") or {}
    records = [rec for rec in snapshot.get("records") or [] if isinstance(rec, dict)]
    print("Timestamp    :", _format_timestamp(snapshot.get("timestamp")))
    print("Records      :", len(records))
    print("Watchlist HL :", meta.get("hyperliquid_watch_count", 0))
    print("Watchlist ETH:", meta.get("etherscan_watch_count", 0))
    print("HL records   :", meta.get("hyperliquid_records", 0))
    print()

    eth_record = next((rec for rec in records if rec.get("metric_name") == "insider_whale_balance_total"), None)
    if eth_record:
        total = eth_record.get("value")
        total_float: float | None = None
        if isinstance(total, Real | str):
            try:
                total_float = float(total)
            except Exception:
                total_float = None
        address_count = len(eth_record.get("addresses") or [])
        print(f"ETH total    : {total_float:.4f}" if isinstance(total_float, float) else "ETH total    : unknown")
        print("ETH addresses:", address_count)
        print()

    positions = _extract_positions(records)
    if not positions:
        print("No Hyperliquid positions recorded.")
        return
    if limit > 0:
        positions = positions[:limit]
    header = f"{'Trader':<18} {'Symbol':<8} {'Side':<6} {'Notional USD':>14} {'Leverage':>9}"
    print(header)
    print("-" * len(header))
    for pos in positions:
        leverage = pos["leverage"]
        leverage_display = f"{float(leverage):.2f}" if isinstance(leverage, Real) else "-"
        print(
            f"{pos['trader']:<18} {pos['symbol']:<8} {pos['side']:<6} "
            f"{pos['notional']:>14,.2f} {leverage_display:>9}"
        )


async def _refresh_snapshot(load_only: bool) -> tuple[dict[str, Any] | None, bool]:
    if load_only:
        return whale_insider.load_latest_snapshot(), False
    snapshot = await whale_insider.fetch_whale_insider_snapshot()
    if snapshot:
        return snapshot, True
    fallback = whale_insider.load_latest_snapshot()
    if fallback:
        log.warning("whale_insider_refresh_failed_using_cache")
    return fallback, False


async def _async_main(args: argparse.Namespace) -> int:
    snapshot, fresh = await _refresh_snapshot(args.load_only)
    if not snapshot:
        log.error("whale_insider_snapshot_unavailable")
        if args.load_only:
            print(
                "No insider snapshot found. Run without --load-only after configuring Hyperliquid and Etherscan",
                file=sys.stderr,
            )
        else:
            print(
                "Failed to refresh insider snapshot. Check Hyperliquid/Etherscan configuration and connectivity.",
                file=sys.stderr,
            )
        return 1
    if args.json:
        payload = {"fresh": fresh, "snapshot": snapshot}
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0
    print("Fresh fetch  :", "yes" if fresh else "no")
    _print_summary(snapshot, limit=args.limit)
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

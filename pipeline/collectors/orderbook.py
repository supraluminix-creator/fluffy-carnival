"""Orderbook depth collector for spot exchanges."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from pipeline.http import async_fetch_json

log = structlog.get_logger(__name__)
_BINANCE_DEPTH_URL = "https://api.binance.com/api/v3/depth"
_VALID_DEPTHS = {5, 10, 20, 50, 100, 500, 1000}


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_orderbook_summary(symbol: str, depth: int = 50, top_n: int = 10) -> dict[str, Any] | None:
    """Fetches top-of-book liquidity and summarises depth zones."""
    if depth not in _VALID_DEPTHS:
        depth = 50
    top_n = max(1, min(top_n, depth))
    try:
        async with httpx.AsyncClient() as client:
            data = await async_fetch_json(
                _BINANCE_DEPTH_URL,
                params={"symbol": symbol.upper(), "limit": depth},
                timeout=5,
                client=client,
            )
    except Exception as exc:  # pragma: no cover - network edge cases
        log.warning("orderbook_fetch_failed", symbol=symbol, error=str(exc))
        return None
    if not isinstance(data, dict):
        return None
    bids = data.get("bids")
    asks = data.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
        return None

    def _summarise(levels: list[Any]) -> dict[str, Any] | None:
        acc: list[tuple[float, float]] = []
        total_quote = 0.0
        top_price = None
        tail_price = None
        for lvl in levels:
            if len(acc) >= top_n:
                break
            if not isinstance(lvl, list | tuple) or len(lvl) < 2:
                continue
            price = _to_float(lvl[0])
            qty = _to_float(lvl[1])
            if price is None or qty is None:
                continue
            if top_price is None:
                top_price = price
            tail_price = price
            total_quote += price * qty
            acc.append((price, qty))
        if not acc or top_price is None or tail_price is None:
            return None
        return {
            "total_quote": total_quote,
            "top": top_price,
            "tail": tail_price,
            "levels": len(acc),
        }

    bids_summary = _summarise(bids)
    asks_summary = _summarise(asks)
    if not bids_summary or not asks_summary:
        return None
    spread = None
    spread_pct = None
    best_bid = bids_summary.get("top")
    best_ask = asks_summary.get("top")
    if isinstance(best_bid, float) and isinstance(best_ask, float):
        spread = best_ask - best_bid
        if best_ask != 0:
            spread_pct = (spread / best_ask) * 100
    return {
        "bid_total_quote": bids_summary["total_quote"],
        "ask_total_quote": asks_summary["total_quote"],
        "bids_zone": bids_summary,
        "asks_zone": asks_summary,
        "spread": spread,
        "spread_pct": spread_pct,
        "source": "binance_spot",
    }


__all__ = ["fetch_orderbook_summary"]

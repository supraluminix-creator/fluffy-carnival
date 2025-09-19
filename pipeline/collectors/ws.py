"""WebSocket collectors: Bybit.

Provides a typed interface for real-time liquidation stream consumption.
Message schema (simplified example from Bybit public docs):

{
  "topic": "liquidation.BTCUSDT",
  "type": "snapshot",
  "ts": 1726680000123,
  "data": [
     {"symbol": "BTCUSDT", "side": "Sell", "price": "56000", "size": "1500", "updatedTime": 1726680000123}
  ]
}

We model only what we consume; extra keys are tolerated via total=False.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any, TypedDict, NotRequired, cast

import websockets


class LiquidationEntry(TypedDict, total=False):
    symbol: str
    side: str  # "Buy" | "Sell"
    price: str  # Provided as string by Bybit
    size: str
    updatedTime: int


class LiquidationMessage(TypedDict, total=False):
    topic: str
    type: str
    ts: int
    data: list[LiquidationEntry]
    # Some payloads may include an extra field like 'creationTime'
    creationTime: NotRequired[int]


MessageHandler = Callable[[LiquidationMessage], None]


async def bybit_ws_liquidations(symbol: str, on_message: MessageHandler | None = None) -> None:
    """Connect to Bybit public WS and stream liquidation events.

    Parameters
    ----------
    symbol: Trading pair symbol, e.g. "BTCUSDT".
    on_message: Optional callback receiving each typed message.
    """
    url = "wss://stream.bybit.com/v5/public/linear"
    subscribe_msg: dict[str, Any] = {"op": "subscribe", "args": [f"liquidation.{symbol}"]}
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps(subscribe_msg))
        while True:
            raw = await ws.recv()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                # Skip malformed frames
                continue
            if not isinstance(parsed, dict):  # Defensive shape check
                continue
            # We tolerate partial payloads; cast after shallow validation
            msg: LiquidationMessage = cast(LiquidationMessage, parsed)
            if on_message:
                on_message(msg)
            else:
                print(msg)


def run_bybit_ws(symbol: str) -> None:
    """Run synchronous entrypoint for liquidation stream."""
    asyncio.run(bybit_ws_liquidations(symbol))
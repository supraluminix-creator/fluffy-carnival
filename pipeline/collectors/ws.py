"""
WebSocket collectors: Bybit WS.
Gère liquidations temps réel, flux dérivés.
"""

import asyncio
import json
from collections.abc import Callable

import websockets


async def bybit_ws_liquidations(symbol: str, on_message: Callable[[dict], None] | None = None):
    """
    Connects to Bybit WebSocket and listens for real-time liquidations.

    Parameters
    ----------
    symbol : str
        Trading pair symbol (e.g., 'BTCUSDT').
    on_message : Callable, optional
        Callback function to process each message (dict).
    """
    url = "wss://stream.bybit.com/v5/public/linear"
    subscribe_msg = {
        "op": "subscribe",
        "args": [f"liquidation.{symbol}"]
    }
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps(subscribe_msg))
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            if on_message:
                on_message(data)
            else:
                print(data)

def run_bybit_ws(symbol: str):
    """
    Run Bybit WebSocket collector for real-time liquidations.
    """
    asyncio.run(bybit_ws_liquidations(symbol))
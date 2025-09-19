#!/usr/bin/env python3
# mypy: ignore-errors
import asyncio
import websockets
import json
from typing import Any

async def fake_bybit_ws(websocket, path: str) -> None:  # type: ignore[no-untyped-def]
    # Simulate a Bybit liquidation event stream
    counter = 0
    print(f"[FAKE SERVER] Client connected from {websocket.remote_address}, starting event stream...")
    try:
        while True:
            # Alternate between single and batch events
            if counter % 2 == 0:
                event = {
                    "topic": "liquidation.BTCUSDT",
                    "data": {"price": 42000 + counter, "qty": 1 + counter, "side": "Sell", "symbol": "BTCUSDT", "ts": 1700000000 + counter}
                }
            else:
                event = {
                    "topic": "liquidation.BTCUSDT",
                    "data": [
                        {"price": 42001 + counter, "qty": 2 + counter, "side": "Buy", "symbol": "BTCUSDT", "ts": 1700000001 + counter},
                        {"price": 42002 + counter, "qty": 3 + counter, "side": "Sell", "symbol": "BTCUSDT", "ts": 1700000002 + counter}
                    ]
                }
            print(f"[FAKE SERVER] Sending event to {websocket.remote_address}: {event}")
            await websocket.send(json.dumps(event))
            await asyncio.sleep(1)
            counter += 1
    except websockets.exceptions.ConnectionClosed:
        print(f"[FAKE SERVER] Client {websocket.remote_address} disconnected.")

async def main() -> None:
    # websockets.serve expects a handler signature (websocket, path)
    server = await websockets.serve(fake_bybit_ws, "localhost", 8765)
    print("Fake Bybit WS server running on ws://localhost:8765")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from typing import Any

import websockets


async def test_client() -> None:
    uri = "ws://localhost:8765"
    async with websockets.connect(uri) as websocket:
        print("[TEST CLIENT] Connected to server.")
        try:
            while True:
                msg: Any = await websocket.recv()
                if isinstance(msg, bytes):
                    try:
                        decoded = msg.decode("utf-8", errors="replace")
                    except Exception:
                        decoded = repr(msg)
                else:
                    decoded = str(msg)
                print(f"[TEST CLIENT] Received: {decoded}")
        except websockets.exceptions.ConnectionClosed:
            print("[TEST CLIENT] Connection closed.")

if __name__ == "__main__":
    asyncio.run(test_client())

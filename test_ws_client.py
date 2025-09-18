import asyncio
import websockets

async def test_client():
    uri = "ws://localhost:8765"
    async with websockets.connect(uri) as websocket:
        print("[TEST CLIENT] Connected to server.")
        try:
            while True:
                msg = await websocket.recv()
                print(f"[TEST CLIENT] Received: {msg}")
        except websockets.exceptions.ConnectionClosed:
            print("[TEST CLIENT] Connection closed.")

if __name__ == "__main__":
    asyncio.run(test_client())

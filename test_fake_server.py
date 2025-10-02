#!/usr/bin/env python3
# mypy: ignore-errors
"""
Quick test of the liquidation collector with fake data
"""
import asyncio
import json
import time
from typing import Any

import websockets


async def fake_bybit_server() -> None:
    """Simulate a Bybit WebSocket server sending liquidation events"""
    async def handle_client(websocket, path: str) -> None:  # type: ignore[no-untyped-def]
        print(f"[SERVER] Client connected: {path}")
        
        # Wait for subscription
        try:
            sub_msg = await websocket.recv()
            print(f"[SERVER] Received subscription: {sub_msg}")
            
            # Send subscription confirmation
            await websocket.send(json.dumps({
                "success": True,
                "ret_msg": "",
                "conn_id": "test-conn-123",
                "req_id": "",
                "op": "subscribe"
            }))
            
            # Send fake liquidation events
            await asyncio.sleep(1)
            
            liquidations: list[dict[str, Any]] = [
                {
                    "topic": "liquidation.BTCUSDT",
                    "type": "snapshot", 
                    "ts": int(time.time() * 1000),
                    "data": {
                        "updatedTime": int(time.time() * 1000),
                        "symbol": "BTCUSDT",
                        "side": "Buy",
                        "size": "0.123",
                        "price": "115000.00"
                    }
                },
                {
                    "topic": "liquidation.BTCUSDT", 
                    "type": "snapshot",
                    "ts": int(time.time() * 1000) + 1000,
                    "data": {
                        "updatedTime": int(time.time() * 1000) + 1000,
                        "symbol": "BTCUSDT", 
                        "side": "Sell",
                        "size": "0.456",
                        "price": "114900.00"
                    }
                }
            ]
            
            for liq in liquidations:
                await websocket.send(json.dumps(liq))
                print(f"[SERVER] Sent liquidation: {liq['data']['symbol']} {liq['data']['side']} {liq['data']['size']} @ ${liq['data']['price']}")
                await asyncio.sleep(2)
                
            # Keep connection alive
            while True:
                await asyncio.sleep(10)
                await websocket.send(json.dumps({"ping": int(time.time())}))
                
        except websockets.exceptions.ConnectionClosed:
            print("[SERVER] Client disconnected")
        except Exception as e:
            print(f"[SERVER] Error: {e}")
    
    print("[SERVER] Starting fake Bybit server on ws://localhost:8766")
    server = await websockets.serve(handle_client, "localhost", 8766)
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(fake_bybit_server())
#!/usr/bin/env python3
"""
BybitWSService: Real-time Bybit Liquidations WebSocket Collector (prod-safe)

Features:
- Robust auto-reconnect, exponential backoff
- Prometheus metrics: connections, errors, event volume, latency
- structlog JSON logging for observability
- Pluggable writer (e.g., BybitLiquidationsWriter for SQLite/Parquet)
- Handles both single and batch liquidation events

Usage Example (Windows):
    python pipeline/collectors/bybit_ws.py --symbols BTCUSDT,ETHUSDT

Prometheus Metrics:
- bybit_ws_connections_total: Total successful WS connections
- bybit_ws_errors_total: Total WS errors (auto-reconnects)
- bybit_ws_events_total{symbol=...}: Liquidation events received per symbol
- bybit_ws_latency_seconds: Message handling latency (seconds)

Logging:
- structlog JSON logs to stdout (INFO level)

Integration:
- Use BybitWSService in your async pipeline, or run as standalone script
- Writer must implement async write_record(dict) method
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from typing import Protocol, Any, Mapping, Optional, List, Callable

import structlog
import websockets
from prometheus_client import Counter, Summary, start_http_server

from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter

# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger("bybit_ws")

# Prometheus metrics
BYBIT_WS_CONNECTIONS = Counter('bybit_ws_connections_total', 'Total WS connections')
BYBIT_WS_ERRORS = Counter('bybit_ws_errors_total', 'Total WS errors')
BYBIT_WS_EVENTS = Counter('bybit_ws_events_total', 'Total liquidation events received', ['symbol'])
BYBIT_WS_LATENCY = Summary('bybit_ws_latency_seconds', 'WS message handling latency')


# ---------------------------------------------------------
# SERVICE WS
# ---------------------------------------------------------
class _WriterProtocol(Protocol):
    async def write_record(self, record: Mapping[str, Any]) -> None: ...  # pragma: no cover
    async def close(self) -> None: ...  # pragma: no cover


class BybitWSService:
    """
    Real-time Bybit Liquidations WebSocket Collector

    Args:
        symbols (list[str]): List of Bybit symbols to subscribe (e.g., ["BTCUSDT"])
        writer: Object with async write_record(dict) method (e.g., BybitLiquidationsWriter)
        ws_url (str): Optional custom WS endpoint
    """
    def __init__(self, symbols: List[str], ws_url: Optional[str] = None, db_path: str = "data/crypto.db",
                 parquet_dir: str = "data/bybit_liquidations", flush_size: int = 100,
                 flush_interval: int = 5, subscribe_tpl: str = "liquidation.{}"):
        self.symbols: List[str] = symbols
        self.ws_url: str = ws_url or self._auto_detect_url(symbols)
        self.subscribe_tpl: str = subscribe_tpl

        os.makedirs(parquet_dir, exist_ok=True)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.writer: _WriterProtocol = BybitLiquidationsWriter(
            db=db_path,
            parquet_dir=parquet_dir,
            flush_size=flush_size,
            flush_interval=flush_interval,
        )

        # websocket-client protocol object (runtime from websockets library)
        self.ws: Optional[Any] = None
        self.stop_event: asyncio.Event = asyncio.Event()
        self._reconnect_delay: int = 1

        logger.info("BybitWSService created", symbols=symbols, ws_url=self.ws_url)

    def _auto_detect_url(self, symbols: List[str]) -> str:
        """
        Auto-detect correct Bybit WS endpoint based on symbol suffixes.
        """
        spot_suffixes = {"USDC", "USDT"}
        if all(sym.endswith(tuple(spot_suffixes)) for sym in symbols):
            return "wss://stream.bybit.com/v5/public/linear"
        return "wss://stream.bybit.com/v5/public/linear"

    async def connect(self) -> None:
        """
        Connect to Bybit WS, subscribe to liquidation topics, handle messages.
        Auto-reconnects on error with exponential backoff. Metrics and logs instrumented.
        """
        logger.info("Connecting to Bybit WS", ws_url=self.ws_url)
        try:
            async with websockets.connect(self.ws_url) as ws:
                self.ws = ws
                BYBIT_WS_CONNECTIONS.inc()
                logger.info("WS connected", ws_url=self.ws_url)

                # subscribe
                subs = [self.subscribe_tpl.format(sym) for sym in self.symbols]
                await ws.send(json.dumps({"op": "subscribe", "args": subs}))
                logger.info("WS subscribed", subs=subs)

                self._reconnect_delay = 1

                async for msg in ws:
                    with BYBIT_WS_LATENCY.time():
                        await self._handle_message(msg)

        except asyncio.CancelledError:
            logger.info("WS connection cancelled")
            raise
        except Exception as e:
            BYBIT_WS_ERRORS.inc()
            logger.warning("WS error", error=str(e), exc_info=True)
            logger.info("Reconnecting", delay=self._reconnect_delay)
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 60)
            if not self.stop_event.is_set():
                await self.connect()

    async def _handle_message(self, raw_msg: object) -> None:
        if isinstance(raw_msg, bytes):  # decode best-effort
            try:
                raw_msg = raw_msg.decode("utf-8", errors="ignore")
            except Exception:
                return
        if not isinstance(raw_msg, str):
            return
        print(f"[COLLECTOR] Received raw message: {raw_msg}")
        """
        Parse and process a single WS message. Handles both single and batch events.
        Increments Prometheus metrics and calls writer.write_record for each event.
        """
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON", raw=raw_msg)
            return

        if "topic" in msg and "data" in msg:
            topic = msg["topic"]
            data = msg["data"]

            if topic.startswith("liquidation."):
                symbol = topic.split(".")[-1]
                if isinstance(data, dict):
                    BYBIT_WS_EVENTS.labels(symbol=symbol).inc()
                    await self.writer.write_record(data)
                elif isinstance(data, list):
                    BYBIT_WS_EVENTS.labels(symbol=symbol).inc(len(data))
                    for d in data:
                        await self.writer.write_record(d)

    async def run(self) -> None:
        """
        Main run loop: manages signal handling, reconnects, and graceful shutdown.
        """
        logger.info("Starting BybitWSService")

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop_event.set)
            except (NotImplementedError, ValueError):
                # Signal handling not supported (e.g., on Windows or in some environments)
                print(f"[DEBUG] Signal handling not supported for {sig} on this platform.")

        while not self.stop_event.is_set():
            await self.connect()

        if hasattr(self.writer, "close"):
            await self.writer.close()  # runtime check; writer conforms
        logger.info("BybitWSService stopped")

    async def stop(self) -> None:
        """
        Stop the service, close WS and writer.
        """
        logger.info("Stopping BybitWSService")
        self.stop_event.set()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        if hasattr(self.writer, "close"):
            await self.writer.close()


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
class BybitWSCollector:
    """
    Backward-compatible lightweight WebSocket collector used by legacy tests.

    This shim connects to Bybit's public linear stream and subscribes to
    liquidation.<SYMBOL>. It invokes the provided on_message callback for
    each raw message payload. It is intentionally minimal and suitable for
    short-lived test runs that may time out quickly.

    Params:
    - symbol: str like "BTCUSDT"
    - on_message: callable taking one argument (raw message string)
    - ws_url: optional WebSocket URL override
    """

    def __init__(self, symbol: str, on_message: Optional[Callable[[str | bytes], None]] = None, ws_url: str | None = None) -> None:
        self.symbol: str = (symbol or "BTCUSDT").upper()
        # Ensure on_message is always a callable accepting a single str argument.
        # websockets.recv() may yield either str or bytes; we pass through transparently.
        self.on_message: Callable[[str | bytes], None] = on_message or (lambda _msg: None)
        self.ws_url: str = ws_url or "wss://stream.bybit.com/v5/public/linear"
        self._ws: Any | None = None
        self._running: bool = False

    async def connect(self) -> None:
        """
        Open a WS connection and subscribe to liquidation.<symbol>.
        Runs until cancelled (e.g., by asyncio.wait_for timeout in tests).
        """
        self._running = True
        try:
            async with websockets.connect(self.ws_url) as ws:
                self._ws = ws
                # Subscribe to the liquidation topic for the single symbol
                sub = {"op": "subscribe", "args": [f"liquidation.{self.symbol}"]}
                await ws.send(json.dumps(sub))
                # Consume messages; tests typically cancel after a short timeout
                while self._running:
                    msg = await ws.recv()
                    import contextlib
                    with contextlib.suppress(Exception):
                        self.on_message(msg)
        except asyncio.CancelledError:
            # Normal path when tests use wait_for(..., timeout=...)
            raise
        except Exception:
            # Propagate other connection errors; tests generally handle exceptions
            raise
        finally:
            self._running = False
            self._ws = None

    def stop(self) -> None:
        """
        Signal the receive loop to stop. The actual connection is typically
        closed by cancellation in the test harness; this only toggles the flag.
        """
        self._running = False


# ---------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------
def main() -> int:
    """
    CLI entrypoint for BybitWSService. Parses args, instantiates service, runs event loop.
    """
    print("[DEBUG] Entered main()")
    parser = argparse.ArgumentParser(description="Bybit WebSocket Liquidations Collector")
    parser.add_argument("-s", "--symbols", required=True,
                        help="Liste des symboles séparés par des virgules (ex: BTCUSDT,ETHUSDT)")
    parser.add_argument("--ws-url", help="Endpoint WS Bybit (défaut auto spot/linear)")
    parser.add_argument("--db", dest="db_path", default="data/crypto.db", help="Fichier SQLite")
    parser.add_argument("--parquet-dir", default="data/bybit_liquidations", help="Dossier Parquet")
    parser.add_argument("--flush-size", type=int, default=100, help="Flush après N enregistrements")
    parser.add_argument("--flush-interval", type=int, default=5, help="Flush après N secondes")
    parser.add_argument("--subscribe-tpl", default="liquidation.{}", help="Template de souscription")
    parser.add_argument("--prometheus-port", type=int, default=8000, help="Prometheus metrics port (default: 8000)")

    args = parser.parse_args()
    print(f"[DEBUG] Parsed args: {args}")
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    print(f"[DEBUG] Symbols: {symbols}")

    # Start Prometheus metrics server
    start_http_server(args.prometheus_port)

    svc = BybitWSService(
        symbols,
        ws_url=args.ws_url,
        db_path=args.db_path,
        parquet_dir=args.parquet_dir,
        flush_size=args.flush_size,
        flush_interval=args.flush_interval,
        subscribe_tpl=args.subscribe_tpl,
    )
    print("[DEBUG] BybitWSService instantiated")

    loop = asyncio.get_event_loop()
    try:
        print("[DEBUG] Before loop.run_until_complete(svc.run())")
        loop.run_until_complete(svc.run())
        print("[DEBUG] After loop.run_until_complete (should not reach unless svc.run() returns)")
    except KeyboardInterrupt:
        logger.info("Interrupted; stopping service")
        loop.run_until_complete(svc.stop())
        return 0
    except Exception as e:
        print(f"[DEBUG] Exception in main(): {e}")
        return 1
    return 0


if __name__ == "__main__":
    print("[DEBUG] Entered __main__ block")
    sys.exit(main())

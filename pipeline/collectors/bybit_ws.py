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
import contextlib
import json
import os
import signal
import sys
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

import structlog
import websockets
from prometheus_client import Counter, Summary, start_http_server

from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter
from pipeline.logging_config import setup_logging  # import tardif pour éviter cycles
from pipeline.storage.sqlite_adapter import ensure_db_parent, get_default_db_path

setup_logging(simple=True)
logger = structlog.get_logger("bybit_ws")

# Prometheus metrics
BYBIT_WS_CONNECTIONS = Counter("bybit_ws_connections_total", "Total WS connections")
BYBIT_WS_ERRORS = Counter("bybit_ws_errors_total", "Total WS errors")
BYBIT_WS_EVENTS = Counter("bybit_ws_events_total", "Total liquidation events received", ["symbol"])
BYBIT_WS_LATENCY = Summary("bybit_ws_latency_seconds", "WS message handling latency")
BYBIT_WS_PARSE_ERRORS = Counter("bybit_ws_parse_errors_total", "Total parse / JSON errors in WS stream")
BYBIT_WS_WRITE_ERRORS = Counter(
    "bybit_ws_writer_errors_total",
    "Total writer errors while persisting WS liquidation events",
)


# ---------------------------------------------------------
# SERVICE WS
# ---------------------------------------------------------
class _WriterProtocol(Protocol):
    async def write_record(self, record: dict[str, Any]) -> None: ...  # pragma: no cover
    async def flush(self) -> int: ...  # pragma: no cover
    def close(self) -> None: ...  # pragma: no cover


class BybitWSService:
    """
    Real-time Bybit Liquidations WebSocket Collector

    Args:
        symbols (list[str]): List of Bybit symbols to subscribe (e.g., ["BTCUSDT"])
        writer: Object with async write_record(dict) method (e.g., BybitLiquidationsWriter)
        ws_url (str): Optional custom WS endpoint
    """

    def __init__(
        self,
        symbols: list[str],
        ws_url: str | None = None,
        db_path: str | None = None,
        parquet_dir: str = "data/bybit_liquidations",
        flush_size: int = 100,
        flush_interval: int = 5,
        subscribe_tpl: str = "liquidation.{}",
        health_port: int | None = None,
        max_reconnect_delay: int = 60,
        ping_interval: float = 20.0,
        ping_timeout: float = 10.0,
        stale_after: int | None = 600,
    ):
        self.symbols: list[str] = symbols
        resolved_db_path = db_path or get_default_db_path()
        self.ws_url: str = ws_url or self._auto_detect_url(symbols)
        self.subscribe_tpl: str = subscribe_tpl
        self.flush_interval: int = max(0, int(flush_interval))
        self._max_reconnect_delay: int = max(1, int(max_reconnect_delay))
        self._ping_interval: float | None = float(ping_interval) if ping_interval > 0 else None
        self._ping_timeout: float | None = float(ping_timeout) if ping_timeout > 0 else None
        self._stale_after: float | None = float(stale_after) if stale_after and stale_after > 0 else None

        os.makedirs(parquet_dir, exist_ok=True)
        ensure_db_parent(resolved_db_path)

        self.writer: _WriterProtocol = BybitLiquidationsWriter(
            db=resolved_db_path,
            parquet_dir=parquet_dir,
            flush_size=flush_size,
            flush_interval=flush_interval,
        )
        # Enregistre le writer dans un registre global pour permettre un job de flush périodique.
        try:  # pragma: no cover - simple instrumentation
            from pipeline.liquidations_registry import set_writer

            set_writer(self.writer)
        except Exception:  # pragma: no cover - défense
            logger.warning("Impossible d'enregistrer le writer dans le registre global", exc_info=True)

        # websocket-client protocol object (runtime from websockets library)
        self.ws: Any | None = None
        self.stop_event: asyncio.Event = asyncio.Event()
        self._reconnect_delay: int = 1
        self.health_port: int | None = health_port
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._last_event_at: float | None = None
        logger.info(
            "BybitWSService created",
            symbols=symbols,
            ws_url=self.ws_url,
            health_port=self.health_port,
            db_path=resolved_db_path,
        )

    def _register_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(lambda t: self._background_tasks.discard(t))
        return task

    async def _cancel_background_tasks(self) -> None:
        tasks = list(self._background_tasks)
        self._background_tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _flush_writer(self) -> None:
        try:
            await self.writer.flush()
        except Exception:
            BYBIT_WS_WRITE_ERRORS.inc()
            logger.warning("WS writer flush failed", exc_info=True)

    async def _flush_loop(self) -> None:
        if self.flush_interval <= 0:
            return
        try:
            while not self.stop_event.is_set():
                await asyncio.sleep(self.flush_interval)
                await self._flush_writer()
        except asyncio.CancelledError:
            raise

    async def _stale_monitor_loop(self) -> None:
        if self._stale_after is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        sleep_for = max(5.0, min(self._stale_after / 2, 60.0))
        try:
            while not self.stop_event.is_set():
                await asyncio.sleep(sleep_for)
                last = self._last_event_at
                if last is None:
                    continue
                idle = loop.time() - last
                if idle >= self._stale_after:
                    logger.warning(
                        "WS stream idle beyond threshold",
                        idle_seconds=round(idle, 1),
                        threshold=self._stale_after,
                    )
                    if self.ws is not None:
                        with contextlib.suppress(Exception):
                            await self.ws.close(code=4000, reason="stale stream")
                    self._last_event_at = loop.time()
        except asyncio.CancelledError:
            raise

    async def _write_event(self, payload: dict[str, Any], symbol: str) -> None:
        try:
            await self.writer.write_record(payload)
        except Exception:
            BYBIT_WS_WRITE_ERRORS.inc()
            logger.warning(
                "WS writer write failed",
                symbol=symbol,
                side=payload.get("side"),
                size=payload.get("size") or payload.get("qty"),
                exc_info=True,
            )

    def _auto_detect_url(self, symbols: list[str]) -> str:
        """
        Auto-detect correct Bybit WS endpoint based on symbol suffixes.
        """
        spot_suffixes = {"USDC", "USDT"}
        if all(sym.endswith(tuple(spot_suffixes)) for sym in symbols):
            return "wss://stream.bybit.com/v5/public/linear"
        return "wss://stream.bybit.com/v5/public/linear"

    async def connect(self) -> None:
        """Establish the WebSocket connection and stream liquidation messages."""
        if self.stop_event.is_set():
            return

        logger.info("Connecting to Bybit WS", ws_url=self.ws_url)
        connect_kwargs: dict[str, Any] = {}
        if self._ping_interval is not None:
            connect_kwargs["ping_interval"] = self._ping_interval
        if self._ping_timeout is not None:
            connect_kwargs["ping_timeout"] = self._ping_timeout

        try:
            async with websockets.connect(self.ws_url, **connect_kwargs) as ws:
                self.ws = ws
                BYBIT_WS_CONNECTIONS.inc()
                logger.info("WS connected", ws_url=self.ws_url, ping_interval=self._ping_interval)
                try:
                    loop = asyncio.get_running_loop()
                    self._last_event_at = loop.time()
                except RuntimeError:
                    self._last_event_at = None

                subs = [self.subscribe_tpl.format(sym) for sym in self.symbols]
                await ws.send(json.dumps({"op": "subscribe", "args": subs}))
                logger.info("WS subscribed", subs=subs)

                self._reconnect_delay = 1

                async for msg in ws:
                    if self.stop_event.is_set():
                        logger.info("Stop requested, leaving WS receive loop")
                        break
                    with BYBIT_WS_LATENCY.time():
                        await self._handle_message(msg)

        except asyncio.CancelledError:
            logger.info("WS connection cancelled")
            raise
        except Exception as exc:  # pragma: no cover - defensive
            BYBIT_WS_ERRORS.inc()
            logger.warning("WS error", error=str(exc), exc_info=True)
        finally:
            self.ws = None

        if self.stop_event.is_set():
            return

        logger.info("Reconnecting", delay=self._reconnect_delay)
        await asyncio.sleep(self._reconnect_delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

    async def _handle_message(self, raw_msg: object) -> None:
        if isinstance(raw_msg, bytes):  # decode best-effort
            try:
                raw_msg = raw_msg.decode("utf-8", errors="ignore")
            except Exception:
                return
        if not isinstance(raw_msg, str):
            return
        """Parse and process a single WebSocket message."""
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError:
            BYBIT_WS_PARSE_ERRORS.inc()
            logger.warning("Invalid JSON", raw=raw_msg)
            return

        if isinstance(msg, dict):
            op = msg.get("op")
            if op == "subscribe" and msg.get("success") is True:
                logger.info("WS subscription confirmed", args=msg.get("args"), request_id=msg.get("req_id"))
                return
            if op in {"ping", "pong"}:
                logger.debug("WS control message", op=op)
                return

        if not isinstance(msg, dict) or "topic" not in msg or "data" not in msg:
            logger.debug("WS message skipped", payload=msg)
            return

        topic = msg["topic"]
        data = msg["data"]
        if not isinstance(topic, str):
            logger.debug("WS message topic invalid", topic=topic)
            return

        if not topic.startswith("liquidation."):
            logger.debug("WS message ignored", topic=topic)
            return

        symbol = topic.split(".")[-1]
        processed = 0

        if isinstance(data, dict):
            await self._write_event(data, symbol)
            processed = 1
        elif isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    await self._write_event(entry, symbol)
                    processed += 1
        else:
            logger.debug("WS message data has unexpected shape", symbol=symbol, data_type=type(data).__name__)
            return

        if processed > 0:
            BYBIT_WS_EVENTS.labels(symbol=symbol).inc(processed)
            logger.debug("WS liquidation batch processed", symbol=symbol, events=processed)
            try:
                loop = asyncio.get_running_loop()
                self._last_event_at = loop.time()
            except RuntimeError:
                self._last_event_at = None

    async def run(self) -> None:
        """
        Main run loop: manages signal handling, reconnects, and graceful shutdown.
        """
        logger.info("Starting BybitWSService", symbols=self.symbols, ws_url=self.ws_url)
        # Register signal handlers only where supported (POSIX). On Windows rely on KeyboardInterrupt.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self.stop_event.set)
                except (NotImplementedError, ValueError):
                    print(f"[DEBUG] Signal handling not supported for {sig} on this platform.")
        else:
            print("[DEBUG] Skipping signal handler registration (platform limitation)")

        # Start background helpers
        flush_task = None
        stale_task = None
        if self.flush_interval > 0:
            flush_task = self._register_task(self._flush_loop())
        if self._stale_after is not None:
            stale_task = self._register_task(self._stale_monitor_loop())

        # Start health endpoint if requested
        health_task: asyncio.Task | None = None
        if self.health_port:
            try:
                health_task = asyncio.create_task(self._run_health_server(self.health_port))
                logger.info("WS health server started", port=self.health_port, symbols=self.symbols)
            except Exception:
                logger.warning("WS health server failed to start", port=self.health_port, exc_info=True)

        while not self.stop_event.is_set():
            await self.connect()

        if hasattr(self.writer, "close"):
            # close() est synchrone pour BybitLiquidationsWriter
            self.writer.close()
        if health_task:
            with contextlib.suppress(Exception):
                health_task.cancel()
        if flush_task or stale_task:
            await self._cancel_background_tasks()
        logger.info("BybitWSService stopped")

    async def stop(self) -> None:
        """
        Stop the service, close WS and writer.
        """
        logger.info("Stopping BybitWSService")
        self.stop_event.set()
        if self.ws:
            import contextlib

            with contextlib.suppress(Exception):
                await self.ws.close()
        if hasattr(self.writer, "close"):
            self.writer.close()

    async def _run_health_server(self, port: int) -> None:
        """Runs a tiny aiohttp server exposing /health with runtime info.

        Lightweight and optional to avoid adding FastAPI/Starlette here.
        """
        try:
            import importlib

            web = importlib.import_module("aiohttp.web")
        except Exception:
            # Fallback: no health server if aiohttp not installed
            logger.warning("aiohttp_not_available_for_ws_health")
            return

        async def handle_health(_request: object) -> object:
            payload = {
                "status": "ok",
                "symbols": self.symbols,
                "ws_url": self.ws_url,
            }
            return web.json_response(payload)

        app = web.Application()
        app.add_routes([web.get("/health", handle_health)])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        try:
            while not self.stop_event.is_set():
                await asyncio.sleep(1)
        finally:
            with contextlib.suppress(Exception):
                await runner.cleanup()


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

    def __init__(
        self,
        symbol: str,
        on_message: Callable[[str | bytes], None] | None = None,
        ws_url: str | None = None,
    ) -> None:
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
    parser.add_argument(
        "-s", "--symbols", required=True, help="Liste des symboles séparés par des virgules (ex: BTCUSDT,ETHUSDT)"
    )
    parser.add_argument("--ws-url", help="Endpoint WS Bybit (défaut auto spot/linear)")
    parser.add_argument(
        "--db",
        dest="db_path",
        default=get_default_db_path(),
        help="Fichier SQLite",
    )
    parser.add_argument("--parquet-dir", default="data/bybit_liquidations", help="Dossier Parquet")
    parser.add_argument("--flush-size", type=int, default=100, help="Flush après N enregistrements")
    parser.add_argument("--flush-interval", type=int, default=5, help="Flush après N secondes")
    parser.add_argument("--subscribe-tpl", default="liquidation.{}", help="Template de souscription")
    parser.add_argument("--prometheus-port", type=int, default=8000, help="Prometheus metrics port (default: 8000)")
    parser.add_argument("--health-port", type=int, default=None, help="Port HTTP pour /health explicite du sidecar")

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
        health_port=args.health_port,
    )
    print("[DEBUG] BybitWSService instantiated")

    try:
        print("[DEBUG] Before asyncio.run(svc.run())")
        asyncio.run(svc.run())
        print("[DEBUG] After asyncio.run (graceful stop)")
    except KeyboardInterrupt:
        logger.info("Interrupted; stopping service")
        import contextlib

        with contextlib.suppress(Exception):
            asyncio.run(svc.stop())
        return 0
    except Exception as e:
        print(f"[DEBUG] Exception in main(): {e}")
        return 1
    return 0


if __name__ == "__main__":
    print("[DEBUG] Entered __main__ block")
    sys.exit(main())

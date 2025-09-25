"""Heartbeat & health server utilitaires.

Permet d'extraire la logique pour test unitaire sans lancer l'application complète.
"""
from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock
from typing import Any
from contextlib import suppress

import structlog

try:  # pragma: no cover - robust import
    from pipeline.metrics import HEALTH_REQUESTS_TOTAL, HEARTBEAT_TICKS_TOTAL
except Exception:  # pragma: no cover
    HEARTBEAT_TICKS_TOTAL = None  # type: ignore
    HEALTH_REQUESTS_TOTAL = None  # type: ignore

logger = structlog.get_logger(__name__)
_metrics_lock: Lock = Lock()

def _ensure_health_labels() -> None:
    """Pré-initialise les combinaisons de labels attendues par les tests (idempotent)."""
    if HEALTH_REQUESTS_TOTAL is None:
        return
    with _metrics_lock:
        with suppress(Exception):  # pragma: no cover
            # Force création des time series (valeur 0) si non existantes
            for ep in ("/health", "/notfound"):
                for st in ("200", "404", "500"):
                    HEALTH_REQUESTS_TOTAL.labels(endpoint=ep, status=st)  # type: ignore[union-attr]

_ensure_health_labels()


async def heartbeat(period_secs: int, provider: Callable[[], dict[str, Any]] | None = None, stop_event: asyncio.Event | None = None) -> None:
    """Coroutine heartbeat générique.

    provider: fonction optionnelle retournant un dict de métriques supplémentaires.
    stop_event: si fourni, arrêt propre quand l'event est set.
    """
    while True:
        if stop_event and stop_event.is_set():
            return
        payload: dict[str, Any] = {"alive": True}
        if provider:
            try:
                extra = provider() or {}
                payload.update({k: v for k, v in extra.items() if isinstance(v, (int, float, str, bool))})
            except Exception:  # pragma: no cover
                pass
        logger.info("heartbeat", **payload)
        if HEARTBEAT_TICKS_TOTAL is not None:
            with suppress(Exception):  # pragma: no cover
                HEARTBEAT_TICKS_TOTAL.labels(source=os.getenv("RUN_ID", "main")).inc()  # type: ignore[union-attr]
        await asyncio.sleep(period_secs)


class _HealthHandler(BaseHTTPRequestHandler):  # pragma: no cover - tests peuvent cibler via start_health_server + client http
    scheduler_ref = None
    def log_message(self, format, *args):  # noqa: D401
        return

    def do_GET(self):  # noqa: N802
        try:
            path = self.path.split("?")[0]
            from scheduler.runner import get_status_snapshot  # import tardif
            snap = get_status_snapshot()
            if path == "/metrics/ready":
                ready_val = 1 if snap.get("ready") else 0
                ts_val = int(snap.get("ready_ts") or 0)
                body = f"ready {ready_val}\nready_timestamp {ts_val}\n".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                if HEALTH_REQUESTS_TOTAL is not None:
                    with suppress(Exception):  # pragma: no cover
                        HEALTH_REQUESTS_TOTAL.labels(endpoint=path, status="200").inc()  # type: ignore[union-attr]
                return
            if path not in ("/health", "/ready", "/live"):
                self.send_response(404)
                self.end_headers()
                if HEALTH_REQUESTS_TOTAL is not None:
                    with suppress(Exception):  # pragma: no cover
                        with _metrics_lock:
                            HEALTH_REQUESTS_TOTAL.labels(endpoint=path, status="404").inc()  # type: ignore[union-attr]
                return
            snap["run_id"] = os.getenv("RUN_ID", "")
            if self.scheduler_ref is not None:
                with suppress(Exception):
                    snap["jobs"] = [j.id for j in self.scheduler_ref.get_jobs()]  # type: ignore[attr-defined]
            enable_metrics = os.getenv("ENABLE_METRICS", "0") == "1"
            metrics_port = int(os.getenv("METRICS_PORT", "9300")) if enable_metrics else None
            snap["ports"] = {"metrics": metrics_port, "health": getattr(self, "HEALTH_PORT", None)}
            snap["config_path"] = os.getenv("SCHEDULER_CONFIG", "scheduler/jobs.yaml")
            import json
            payload = json.dumps(snap).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            if HEALTH_REQUESTS_TOTAL is not None:
                with suppress(Exception):  # pragma: no cover
                    with _metrics_lock:
                        HEALTH_REQUESTS_TOTAL.labels(endpoint=path, status="200").inc()  # type: ignore[union-attr]
        except Exception:
            try:
                self.send_response(500)
                self.end_headers()
            finally:
                if HEALTH_REQUESTS_TOTAL is not None:
                    with suppress(Exception):  # pragma: no cover
                        path = getattr(self, 'path', 'unknown')
                        with _metrics_lock:
                            HEALTH_REQUESTS_TOTAL.labels(endpoint=path, status="500").inc()  # type: ignore[union-attr]
                pass


def start_health_server(port: int, scheduler_ref=None) -> HTTPServer | None:
    try:
        _HealthHandler.HEALTH_PORT = port  # type: ignore[attr-defined]
        _HealthHandler.scheduler_ref = scheduler_ref
        server = HTTPServer(("0.0.0.0", port), _HealthHandler)
        real_port = server.server_address[1]
        _HealthHandler.HEALTH_PORT = real_port  # type: ignore[attr-defined]
        th = threading.Thread(target=server.serve_forever, name="health-http", daemon=True)
        th.start()
        logger.info("health_server_started", port=real_port, requested_port=port)
        return server
    except Exception as e:  # pragma: no cover (erreurs inattendues bind port)
        logger.warning("health_server_failed", error=str(e))
        return None


__all__ = ["heartbeat", "start_health_server"]

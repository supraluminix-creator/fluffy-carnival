"""API endpoints pour monitoring et observabilité du système crypto monitor."""

import os
import time
from typing import Any

import psutil
import structlog
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

logger = structlog.get_logger(__name__)


# FastAPI app
app = FastAPI(
    title="Crypto Monitor API",
    version="1.0.0",
    description="Health checks et métriques pour le monitoring crypto",
)


# Variables globales pour tracking
startup_time = time.time()
scheduler_instance = None
collectors_registry = {}


def register_scheduler(scheduler):
    """Enregistre l'instance du scheduler pour monitoring."""
    global scheduler_instance
    scheduler_instance = scheduler
    logger.info("Scheduler registered with health API")


def register_collectors(collectors: dict[str, Any]):
    """Enregistre les collectors pour monitoring."""
    global collectors_registry
    collectors_registry = collectors
    logger.info("Collectors registered with health API", count=len(collectors))


@app.get("/health")
async def health_check():
    """Health check endpoint pour load balancers et monitoring externe.

    Returns:
        JSON avec status global et détail par collector
    """
    try:
        collectors_status = await get_collectors_health()
        scheduler_info = get_scheduler_health()

        # Déterminer status global
        collector_health = all(
            c.get("status") == "healthy" for c in collectors_status.values()
        )
        scheduler_health = scheduler_info.get("status") == "healthy"

        overall_status = (
            "healthy" if (collector_health and scheduler_health) else "degraded"
        )

        response = {
            "status": overall_status,
            "timestamp": time.time(),
            "uptime_seconds": int(time.time() - startup_time),
            "version": "1.0.0",
            "scheduler": scheduler_info,
            "collectors": collectors_status,
        }

        logger.info("Health check requested", status=overall_status)
        return response

    except Exception as e:  # noqa: BLE001
        logger.error("Health check failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Health check failed",
        ) from e


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint pour scraping.

    Returns:
        Métriques au format Prometheus
    """
    try:
        metrics_data = generate_latest()
        logger.debug("Prometheus metrics served")
        return Response(
            content=metrics_data,
            media_type=CONTENT_TYPE_LATEST,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Metrics generation failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Metrics generation failed",
        ) from e


@app.get("/status")
async def detailed_status():
    """Status détaillé pour debugging et diagnostics.

    Returns:
        JSON avec informations système détaillées
    """
    try:
        return {
            "system": get_system_info(),
            "uptime": int(time.time() - startup_time),
            "scheduler": get_scheduler_detailed_info(),
            "collectors": await get_collectors_detailed_status(),
            "performance": get_performance_metrics(),
            "environment": get_environment_info(),
        }
    except Exception as e:  # noqa: BLE001
        logger.error("Status check failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Status check failed",
        ) from e


@app.get("/")
async def root():
    """Page d'accueil avec informations de base."""
    return {
        "service": "Crypto Monitor",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": " /health",
            "metrics": "/metrics",
            "status": "/status",
        },
    }


async def get_collectors_health() -> dict[str, dict[str, Any]]:
    """Vérifie la santé de chaque collector."""
    health_status: dict[str, dict[str, Any]] = {}

    for name, collector in collectors_registry.items():
        try:
            # Vérifier si le collector a des métriques récentes
            last_success = getattr(collector, "last_success_time", None)
            last_error = getattr(collector, "last_error_time", None)

            current_time = time.time()
            is_recent_success = (
                last_success
                and (current_time - last_success) < 1800
            )  # 30 min
            is_recent_error = (
                last_error and (current_time - last_error) < 300
            )  # 5 min

            if is_recent_success and not is_recent_error:
                status = "healthy"
            elif is_recent_error:
                status = "error"
            else:
                status = "unknown"

            health_status[name] = {
                "status": status,
                "last_success": last_success,
                "last_error": last_error,
                "cache_enabled": hasattr(collector, "cache"),
            }
        except Exception as e:  # noqa: BLE001
            health_status[name] = {"status": "error", "error": str(e)}

    return health_status


def get_scheduler_health() -> dict[str, Any]:
    """Vérifie la santé du scheduler."""
    if not scheduler_instance:
        return {"status": "not_configured"}

    try:
        info = scheduler_instance.get_scheduler_info()
        is_running = info.get("running", False)
        job_count = info.get("job_count", 0)
        status = "healthy" if (is_running and job_count > 0) else "degraded"
        return {
            "status": status,
            "running": is_running,
            "job_count": job_count,
        }
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e)}


def get_scheduler_detailed_info() -> dict[str, Any]:
    """Info détaillée du scheduler."""
    if not scheduler_instance:
        return {"configured": False}

    try:
        return {"configured": True, **scheduler_instance.get_scheduler_info()}
    except Exception as e:  # noqa: BLE001
        return {"configured": True, "error": str(e)}


async def get_collectors_detailed_status() -> dict[str, dict[str, Any]]:
    """Status détaillé des collectors."""
    detailed_status: dict[str, dict[str, Any]] = {}

    for name, collector in collectors_registry.items():
        try:
            metrics: dict[str, Any] = {}
            if hasattr(collector, "metrics"):
                metrics = collector.metrics

            detailed_status[name] = {
                "class": collector.__class__.__name__,
                "metrics": metrics,
                "cache_stats": getattr(collector, "cache_stats", {}),
                "config": {
                    "name": getattr(collector, "name", name),
                    "timeout": getattr(collector, "timeout", None),
                },
            }
        except Exception as e:  # noqa: BLE001
            detailed_status[name] = {"error": str(e)}

    return detailed_status


def get_system_info() -> dict[str, Any]:
    """Informations système."""
    try:
        process = psutil.Process()
        return {
            "cpu_percent": process.cpu_percent(),
            "memory_mb": round(process.memory_info().rss / 1024 / 1024, 1),
            "threads": process.num_threads(),
            "open_files": len(process.open_files()),
            "pid": process.pid,
        }
    except Exception:  # noqa: BLE001
        return {"error": "Unable to get system info"}


def get_performance_metrics() -> dict[str, Any]:
    """Métriques de performance."""
    return {
        "uptime_seconds": int(time.time() - startup_time),
        "collectors_count": len(collectors_registry),
        "scheduler_configured": scheduler_instance is not None,
    }


def get_environment_info() -> dict[str, Any]:
    """Informations environnement (sans secrets)."""
    env_info: dict[str, Any] = {}

    public_env_vars = [
        "COLLECTOR_INTERVAL_MARKET",
        "COLLECTOR_INTERVAL_DEFILLAMA",
        "COLLECTOR_INTERVAL_ONCHAIN",
        "COLLECTOR_INTERVAL_DERIVATIVES",
        "COLLECTOR_INTERVAL_SENTIMENT",
        "SCHEDULER_JITTER_PERCENT",
        "API_HOST",
        "API_PORT",
    ]

    for var in public_env_vars:
        env_info[var] = os.getenv(var, "not_set")

    return env_info
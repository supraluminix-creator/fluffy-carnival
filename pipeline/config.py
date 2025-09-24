"""Module centralisé de configuration.

Fournit un point unique pour lire et valider les variables d'environnement.
Utilisation:
    from pipeline.config import get_config
    cfg = get_config()
    if cfg.enable_metrics: ...
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from typing import List, Optional


def get_env_str(name: str, default: Optional[str] = None, *, required: bool = False) -> Optional[str]:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise ValueError(f"Environment variable '{name}' is required but missing")
    return value


def get_env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_env_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        val = int(raw)
    except ValueError as e:  # pragma: no cover
        raise ValueError(f"Invalid int for {name}: {raw}") from e
    if min_value is not None and val < min_value:
        raise ValueError(f"{name} must be >= {min_value}")
    if max_value is not None and val > max_value:
        raise ValueError(f"{name} must be <= {max_value}")
    return val


def get_env_list(name: str, default: Optional[List[str]] = None, sep: str = ",") -> List[str]:
    raw = os.getenv(name)
    if raw is None:
        return default or []
    parts = [p.strip() for p in raw.split(sep)]
    return [p for p in parts if p]


@dataclass(frozen=True)
class AppConfig:
    mode: str
    enable_scheduler: bool
    scheduler_config: str
    run_jobs_at_start: bool
    heartbeat_secs: int
    enable_metrics: bool
    metrics_port: int
    enable_health: bool
    health_port: int
    scheduler_jitter_percent: int
    run_id: Optional[str]
    cb_threshold: int
    cb_cooldown_seconds: int


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig(
        mode=get_env_str("CRYPTO_MONITOR_MODE", "scheduler") or "scheduler",
        enable_scheduler=get_env_bool("ENABLE_SCHEDULER", True),
        scheduler_config=get_env_str("SCHEDULER_CONFIG", "scheduler/jobs.yaml") or "scheduler/jobs.yaml",
        run_jobs_at_start=get_env_bool("RUN_JOBS_AT_START", True),
        heartbeat_secs=get_env_int("HEARTBEAT_SECS", 60, min_value=1),
        enable_metrics=get_env_bool("ENABLE_METRICS", False),
        metrics_port=get_env_int("METRICS_PORT", 9300, min_value=1),
        enable_health=get_env_bool("ENABLE_HEALTH", True),
        health_port=get_env_int("HEALTH_PORT", 9310, min_value=1),
        scheduler_jitter_percent=get_env_int("SCHEDULER_JITTER_PERCENT", 10, min_value=0, max_value=100),
        run_id=get_env_str("RUN_ID"),
        cb_threshold=get_env_int("CB_THRESHOLD", 3, min_value=1),
        cb_cooldown_seconds=get_env_int("CB_COOLDOWN_SECONDS", 30, min_value=1),
    )


def refresh_config_cache() -> None:
    get_config.cache_clear()  # type: ignore[attr-defined]


__all__ = [
    "get_config",
    "refresh_config_cache",
    "get_env_str",
    "get_env_bool",
    "get_env_int",
    "get_env_list",
    "AppConfig",
]

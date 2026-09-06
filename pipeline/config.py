"""Module centralisé de configuration.

Fournit un point unique pour lire et valider les variables d'environnement.
Utilisation:
    from pipeline.config import get_config
    cfg = get_config()
    if cfg.enable_metrics: ...
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def get_env_str(name: str, default: str | None = None, *, required: bool = False) -> str | None:
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


def get_env_list(name: str, default: list[str] | None = None, sep: str = ",") -> list[str]:
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
    run_id: str | None
    cb_threshold: int
    cb_cooldown_seconds: int


class YamlConfig:
    """YAML configuration loader with environment overrides."""

    def __init__(self, config_file: str | Path):
        self.config_file = Path(config_file)
        self._config: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration from YAML file."""
        if self.config_file.exists():
            with open(self.config_file, encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        else:
            self._config = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value with environment override."""
        # Check environment variable first (KEY_SUBKEY format)
        env_key = key.upper().replace(".", "_").replace("/", "_")
        env_value = os.getenv(env_key)
        if env_value is not None:
            # Try to convert to appropriate type
            if env_value.isdigit():
                return int(env_value)
            elif env_value.replace(".", "").isdigit():
                return float(env_value)
            elif env_value.lower() in ("true", "false"):
                return env_value.lower() == "true"
            return env_value

        # Navigate nested dict
        keys = key.split(".")
        value = self._config
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def get_timeout(self, collector: str) -> float:
        """Get timeout for specific collector."""
        return float(self.get(f"timeouts.{collector}", self.get("timeouts.default", 8.0)))

    def get_rate_limit(self, api: str) -> int:
        """Get rate limit for specific API."""
        return int(self.get(f"rate_limits.{api}", self.get("rate_limits.default", 10)))

    def get_interval(self, collector: str) -> int:
        """Get interval for specific collector."""
        return int(self.get(f"intervals.{collector}", 300))


# Global YAML config instance
_yaml_config: YamlConfig | None = None


def get_yaml_config() -> YamlConfig:
    """Get global YAML config instance."""
    global _yaml_config
    if _yaml_config is None:
        config_path = os.getenv("SCHEDULER_CONFIG", "scheduler/config.yaml")
        # Use the directory of the config file
        config_dir = Path(config_path).parent
        yaml_path = config_dir / "config.yaml"
        _yaml_config = YamlConfig(yaml_path)
    return _yaml_config


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
    "get_yaml_config",
    "get_env_str",
    "get_env_bool",
    "get_env_int",
    "get_env_list",
    "AppConfig",
    "YamlConfig",
]

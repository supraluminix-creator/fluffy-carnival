"""
BaseCollector for prod-safe collectors with fallback, retry/backoff, logging, Prometheus, and cache TTL.
"""

import time
from typing import Any, Protocol, TypedDict, runtime_checkable

import structlog
from diskcache import Cache
from prometheus_client import Counter, Gauge
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.config import get_yaml_config
from pipeline.metrics.collectors import CACHE_HITS_TOTAL, CACHE_MISSES_TOTAL, COLLECTOR_LATENCY_SECONDS

log = structlog.get_logger()
cache = Cache(".cache")  # type: ignore[assignment]


class CollectorResult(TypedDict, total=False):
    timestamp: int | None
    metric_name: str
    value: Any
    source: str
    confidence_score: float | None


@runtime_checkable
class BaseCollectorProtocol(Protocol):  # pragma: no cover - structural only
    async def fetch(self, *args: Any, **kwargs: Any) -> Any | None: ...  # noqa: D401


class BaseCollector:
    """
    Base class for all collectors. Handles retry, logging, Prometheus, and cache TTL.
    Subclasses must implement async fetch_main() and fetch_backup().
    """

    COLLECTOR_ERRORS = Counter("collector_errors_total", "Total collector errors", ["collector"])
    COLLECTOR_SUCCESS = Counter("collector_success_total", "Total collector successes", ["collector"])
    COLLECTOR_LAST_SUCCESS_TS = Gauge(
        "collector_last_success_timestamp",
        "Epoch timestamp of last successful collector fetch",
        ["collector"],
    )

    def __init__(self, name: str = "unnamed", cache_ttl: int = 300):
        # name optionnel pour compat avec anciens tests instanciant sans paramètre
        self.name = name or "unnamed"
        self.cache_ttl = cache_ttl
        self.cache = cache
        self.log = log.bind(collector=name)
        self._yaml_config = get_yaml_config()

    def get_timeout(self) -> float:
        """Get configurable timeout for this collector from YAML config."""
        return self._yaml_config.get_timeout(self.name)

    async def fetch(self, *args: Any, **kwargs: Any) -> Any | None:
        key = f"{self.name}_" + "_".join(map(str, args))
        if key in self.cache:  # membership supported by diskcache
            CACHE_HITS_TOTAL.labels(collector=self.name).inc()
            self.log.info("cache_hit", key=key)
            # Use .get to satisfy type checker instead of direct indexing
            return self.cache.get(key, None)
        CACHE_MISSES_TOTAL.labels(collector=self.name).inc()
        start_time = time.time()
        try:
            result = await self._fetch_with_fallback(*args, **kwargs)
            latency = time.time() - start_time
            COLLECTOR_LATENCY_SECONDS.labels(collector=self.name).observe(latency)
            if result is not None:
                self.cache.set(key, result, expire=self.cache_ttl)
                self.COLLECTOR_SUCCESS.labels(self.name).inc()
                from contextlib import suppress

                with suppress(Exception):  # pragma: no cover - ne jamais casser le flux pour une gauge
                    self.COLLECTOR_LAST_SUCCESS_TS.labels(self.name).set(int(time.time()))
                self.log.info("success", key=key)
            else:
                self.COLLECTOR_ERRORS.labels(self.name).inc()
                self.log.error("no_result", key=key)
            return result
        except Exception as e:
            latency = time.time() - start_time
            COLLECTOR_LATENCY_SECONDS.labels(collector=self.name).observe(latency)
            self.COLLECTOR_ERRORS.labels(self.name).inc()
            self.log.error("collector_error", key=key, error=str(e))
            return None

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
    async def _fetch_with_fallback(self, *args: Any, **kwargs: Any) -> Any | None:
        try:
            return await self.fetch_main(*args, **kwargs)
        except Exception as e:
            self.log.warning("main_failed", error=str(e))
            try:
                return await self.fetch_backup(*args, **kwargs)
            except Exception as e2:
                self.log.error("backup_failed", error=str(e2))
                return None

    async def fetch_main(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("fetch_main must be implemented by subclass")

    async def fetch_backup(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("fetch_backup must be implemented by subclass")

    # Compat héritée (anciens tests synchrones) : interface minimale .collect()
    # Les implémentations modernes devraient utiliser les méthodes async.
    def collect(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        raise NotImplementedError("collect() non implémenté: utiliser fetch_main/fetch_backup async")


__all__ = [
    "BaseCollector",
    "BaseCollectorProtocol",
    "CollectorResult",
]

"""
BaseCollector for prod-safe collectors with fallback, retry/backoff, logging, Prometheus, and cache TTL.
"""
from typing import Any, Protocol, runtime_checkable, TypedDict

import structlog
from diskcache import Cache
from prometheus_client import Counter, Summary
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()
cache: Cache[Any, Any] = Cache(".cache")

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
    COLLECTOR_LATENCY = Summary('collector_latency_seconds', 'Latency of collector calls', ['collector'])
    COLLECTOR_ERRORS = Counter('collector_errors_total', 'Total collector errors', ['collector'])
    COLLECTOR_SUCCESS = Counter('collector_success_total', 'Total collector successes', ['collector'])

    def __init__(self, name: str, cache_ttl: int = 300):
        self.name = name
        self.cache_ttl = cache_ttl
        self.cache = cache
        self.log = log.bind(collector=name)

    async def fetch(self, *args: Any, **kwargs: Any) -> Any | None:
        key = f"{self.name}_" + "_".join(map(str, args))
        if key in self.cache:  # membership supported by diskcache
            self.log.info("cache_hit", key=key)
            # Use .get to satisfy type checker instead of direct indexing
            return self.cache.get(key, None)
        try:
            with self.COLLECTOR_LATENCY.labels(self.name).time():
                result = await self._fetch_with_fallback(*args, **kwargs)
            if result is not None:
                self.cache.set(key, result, expire=self.cache_ttl)
                self.COLLECTOR_SUCCESS.labels(self.name).inc()
                self.log.info("success", key=key)
            else:
                self.COLLECTOR_ERRORS.labels(self.name).inc()
                self.log.error("no_result", key=key)
            return result
        except Exception as e:
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

__all__ = [
    "BaseCollector",
    "BaseCollectorProtocol",
    "CollectorResult",
]

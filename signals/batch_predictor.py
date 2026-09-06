# signals/batch_predictor.py
"""Batch prediction system for high-throughput ML inference with Redis caching."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import structlog
from diskcache import Cache

from pipeline.redis_cache import RedisCache
from .ml_predictor import PredictorUnavailable, SignalFeatures, SignalPredictor

logger = structlog.get_logger(__name__)


@dataclass
class BatchPredictionRequest:
    """Request for batch prediction with caching."""

    features: SignalFeatures
    cache_key: str
    timestamp: float

    @classmethod
    def from_features(cls, features: SignalFeatures) -> BatchPredictionRequest:
        """Create request with computed cache key."""
        # Create deterministic cache key from features
        feature_str = json.dumps(features.as_vector(), sort_keys=True)
        cache_key = hashlib.sha256(feature_str.encode()).hexdigest()[:16]
        return cls(features=features, cache_key=cache_key, timestamp=time.time())


@dataclass
class BatchPredictionResult:
    """Result of batch prediction."""

    confidence: float
    cache_hit: bool
    processing_time: float
    batch_size: int


class BatchPredictorUnavailable(RuntimeError):
    """Raised when batch predictor cannot serve requests."""


class BatchPredictor:
    """High-throughput batch prediction system with Redis caching."""

    def __init__(
        self,
        model_path: Optional[Path] = None,
        batch_size: int = 32,
        max_queue_size: int = 1000,
        cache_ttl: int = 3600,
        redis_url: Optional[str] = None,
    ):
        self._model_path = model_path or Path(os.getenv("ML_MODEL_PATH", "models/reversal_model.pkl"))
        self._batch_size = batch_size
        self._max_queue_size = max_queue_size
        self._cache_ttl = cache_ttl
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")

        # Core components
        self._model: Optional[Any] = None
        self._cache: Optional[RedisCache] = None
        self._prediction_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._batch_processor_task: Optional[asyncio.Task] = None

        # Metrics
        self._total_predictions = 0
        self._cache_hits = 0
        self._processing_times: deque = deque(maxlen=1000)
        self._last_error: Optional[str] = None

        # Async locks
        self._model_lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        """Check if batch processor is running."""
        return self._batch_processor_task is not None and not self._batch_processor_task.done()

    @property
    def queue_size(self) -> int:
        """Current queue size."""
        return self._prediction_queue.qsize()

    @property
    def cache_hit_rate(self) -> float:
        """Cache hit rate (0.0 to 1.0)."""
        if self._total_predictions == 0:
            return 0.0
        return self._cache_hits / self._total_predictions

    @property
    def avg_processing_time(self) -> float:
        """Average processing time in milliseconds."""
        if not self._processing_times:
            return 0.0
        return sum(self._processing_times) / len(self._processing_times) * 1000

    async def start(self) -> None:
        """Start the batch prediction processor."""
        if self.is_running:
            return

        await self._ensure_model()
        await self._ensure_cache()

        self._batch_processor_task = asyncio.create_task(self._batch_processor_loop())
        logger.info("batch_predictor_started", batch_size=self._batch_size, max_queue=self._max_queue_size)

    async def stop(self) -> None:
        """Stop the batch prediction processor."""
        if self._batch_processor_task:
            self._batch_processor_task.cancel()
            try:
                await self._batch_processor_task
            except asyncio.CancelledError:
                pass
            self._batch_processor_task = None

        if self._cache:
            async with self._cache_lock:
                self._cache.close()
                self._cache = None

        logger.info("batch_predictor_stopped")

    async def predict(self, features: SignalFeatures) -> float:
        """Submit prediction request and wait for result."""
        if not self.is_running:
            raise BatchPredictorUnavailable("Batch predictor not running")

        request = BatchPredictionRequest.from_features(features)

        # Check cache first
        async with self._cache_lock:
            cached_result = self._cache.get(f"pred:{request.cache_key}")
            if cached_result is not None:
                self._cache_hits += 1
                self._total_predictions += 1
                return cached_result

        # Submit to queue
        future: asyncio.Future[float] = asyncio.Future()
        await self._prediction_queue.put((request, future))

        # Wait for result with timeout
        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            raise BatchPredictorUnavailable("Prediction timeout")

    async def _batch_processor_loop(self) -> None:
        """Main batch processing loop."""
        while True:
            try:
                # Collect batch
                batch = await self._collect_batch()

                if not batch:
                    await asyncio.sleep(0.01)  # Small delay when queue empty
                    continue

                # Process batch
                start_time = time.time()
                results = await self._process_batch(batch)
                processing_time = time.time() - start_time

                # Update metrics
                batch_size = len(batch)
                avg_time_per_pred = processing_time / batch_size
                for _ in range(batch_size):
                    self._processing_times.append(avg_time_per_pred)

                # Deliver results
                await self._deliver_results(batch, results)

                logger.debug(
                    "batch_processed",
                    batch_size=batch_size,
                    processing_time_ms=processing_time * 1000,
                    avg_time_per_pred_ms=avg_time_per_pred * 1000,
                    queue_size=self.queue_size
                )

            except Exception as exc:
                self._last_error = str(exc)
                logger.error("batch_processing_error", error=str(exc))
                await asyncio.sleep(1.0)  # Backoff on errors

    async def _collect_batch(self) -> List[Tuple[BatchPredictionRequest, asyncio.Future[float]]]:
        """Collect a batch of prediction requests."""
        batch = []

        # Get first request (blocking)
        try:
            request, future = await asyncio.wait_for(
                self._prediction_queue.get(),
                timeout=1.0
            )
            batch.append((request, future))
        except asyncio.TimeoutError:
            return batch  # Empty batch

        # Get remaining requests (non-blocking)
        for _ in range(self._batch_size - 1):
            try:
                request, future = self._prediction_queue.get_nowait()
                batch.append((request, future))
            except asyncio.QueueEmpty:
                break

        return batch

    async def _process_batch(
        self,
        batch: List[Tuple[BatchPredictionRequest, asyncio.Future[float]]]
    ) -> List[float]:
        """Process a batch of prediction requests."""
        if not batch:
            return []

        async with self._model_lock:
            model = await self._ensure_model()

            # Extract feature vectors
            feature_vectors = []
            for request, _ in batch:
                feature_vectors.append(request.features.as_vector())

            # Batch prediction
            try:
                vectors_array = np.array(feature_vectors)
                probabilities = model.predict_proba(vectors_array)
                confidences = probabilities[:, 1].astype(float)

                return confidences.tolist()

            except Exception as exc:
                self._last_error = str(exc)
                logger.error("batch_prediction_failed", error=str(exc), batch_size=len(batch))
                raise BatchPredictorUnavailable("Batch prediction failed") from exc

    async def _deliver_results(
        self,
        batch: List[Tuple[BatchPredictionRequest, asyncio.Future[float]]],
        results: List[float]
    ) -> None:
        """Deliver results to waiting futures and cache them."""
        cache_operations = []

        for (request, future), confidence in zip(batch, results):
            # Cache result
            cache_operations.append((f"pred:{request.cache_key}", confidence, self._cache_ttl))

            # Set future result
            if not future.done():
                future.set_result(confidence)

            self._total_predictions += 1

        # Batch cache set operations
        async with self._cache_lock:
            for key, value, ttl in cache_operations:
                self._cache.set(key, value, ttl)

    async def _ensure_model(self) -> Any:
        """Ensure model is loaded."""
        if self._model is not None:
            return self._model

        try:
            async with self._model_lock:
                if self._model is None:  # Double-check
                    self._model = joblib.load(self._model_path)
                    logger.info("batch_model_loaded", path=str(self._model_path))
                return self._model
        except Exception as exc:
            self._last_error = str(exc)
            logger.error("batch_model_load_failed", path=str(self._model_path), error=str(exc))
            raise BatchPredictorUnavailable(f"Unable to load model: {self._model_path}") from exc

    async def _ensure_cache(self) -> RedisCache:
        """Ensure Redis cache is initialized."""
        if self._cache is not None:
            return self._cache

        try:
            async with self._cache_lock:
                if self._cache is None:  # Double-check
                    cache_dir = Path("data/batch_cache")
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    disk_cache = Cache(str(cache_dir))
                    self._cache = RedisCache(disk_cache)
                    logger.info("batch_cache_initialized", redis_url=self._redis_url)
                return self._cache
        except Exception as exc:
            logger.warning("batch_cache_init_failed", error=str(exc))
            raise BatchPredictorUnavailable("Cache initialization failed") from exc


# Global batch predictor instance
_BATCH_PREDICTOR: Optional[BatchPredictor] = None


async def get_batch_predictor() -> BatchPredictor:
    """Get global batch predictor instance."""
    global _BATCH_PREDICTOR
    if _BATCH_PREDICTOR is None:
        _BATCH_PREDICTOR = BatchPredictor()
        await _BATCH_PREDICTOR.start()
    return _BATCH_PREDICTOR


async def reset_batch_predictor() -> None:
    """Reset global batch predictor."""
    global _BATCH_PREDICTOR
    if _BATCH_PREDICTOR is not None:
        await _BATCH_PREDICTOR.stop()
        _BATCH_PREDICTOR = None


__all__ = [
    "BatchPredictionRequest",
    "BatchPredictionResult",
    "BatchPredictorUnavailable",
    "BatchPredictor",
    "get_batch_predictor",
    "reset_batch_predictor",
]

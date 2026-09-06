"""Machine learning predictor for TradingView swing reversal signals."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import structlog
from diskcache import Cache

from pipeline.redis_cache import RedisCache

logger = structlog.get_logger(__name__)


class PredictorUnavailable(RuntimeError):
    """Raised when the ML predictor cannot serve a request."""


@dataclass
class SignalFeatures:
    """Normalized feature vector consumed by the ML model."""

    price: float
    rsi: float
    volume_ratio: float
    fvg: int
    divergence: int
    mtf: int

    def as_vector(self) -> list[float]:
        return [
            float(self.price),
            float(self.rsi),
            float(self.volume_ratio),
            float(self.fvg),
            float(self.divergence),
            float(self.mtf),
        ]


def _default_model_path() -> Path:
    path = os.getenv("ML_MODEL_PATH", "models/reversal_model.pkl")
    return Path(path)


def _default_backlog_path() -> Path:
    path = os.getenv("SIGNALS_BACKLOG_PATH", "data/signal_backlog")
    return Path(path)


class SignalPredictor:
    """Handles ML model lifecycle with disk-backed fallback cache."""

    def __init__(self, model_path: Path | None = None, backlog_path: Path | None = None) -> None:
        self._model_path = model_path or _default_model_path()
        self._backlog_path = backlog_path or _default_backlog_path()
        self._model: Any | None = None
        # Ensure parent directory exists lazily when needed
        self._cache: Any | None = None
        self._last_error: str | None = None

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def backlog_size(self) -> int:
        cache = self._ensure_cache()
        if cache is None:
            return 0
        try:
            return len(cache)
        except Exception:  # pragma: no cover - disk issues are rare
            return 0

    def predict(self, features: SignalFeatures) -> float:
        try:
            model = self._ensure_model()
        except PredictorUnavailable as exc:
            self._store_backlog(features)
            raise exc

        try:
            vector = [features.as_vector()]
            proba = model.predict_proba(vector)[0][1]
            self._last_error = None
            return float(proba)
        except Exception as exc:  # pragma: no cover - hard failure path
            self._last_error = str(exc)
            self._store_backlog(features)
            logger.error("signal_prediction_failed", error=str(exc))
            raise PredictorUnavailable("prediction failed") from exc

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        path = self._model_path
        try:
            model = joblib.load(path)
        except Exception as exc:
            self._last_error = str(exc)
            logger.error("ml_model_load_failed", path=str(path), error=str(exc))
            raise PredictorUnavailable(f"Unable to load model: {path}") from exc
        self._model = model
        self._last_error = None
        return model

    def _ensure_cache(self) -> Any | None:
        if self._cache is not None:
            return self._cache
        try:
            self._backlog_path.mkdir(parents=True, exist_ok=True)
            disk_cache = Cache(str(self._backlog_path))
            cache = RedisCache(disk_cache)
        except Exception as exc:  # pragma: no cover - disk issues are rare
            logger.warning("signal_backlog_unavailable", error=str(exc))
            self._cache = None
            return None
        self._cache = cache
        return cache

    def _store_backlog(self, features: SignalFeatures | None) -> None:
        cache = self._ensure_cache()
        if cache is None:
            return
        payload = {"features": features.as_vector() if features else None}
        try:
            cache.set(uuid.uuid4().hex, payload, expire=int(os.getenv("SIGNALS_BACKLOG_TTL", "86400")))
        except Exception as exc:  # pragma: no cover - disk issues are rare
            logger.warning("signal_backlog_write_failed", error=str(exc))

    def close(self) -> None:
        if self._cache is not None:
            self._cache.close()
            self._cache = None


_PREDICTOR: SignalPredictor | None = None


def get_predictor() -> SignalPredictor:
    global _PREDICTOR
    if _PREDICTOR is None:
        _PREDICTOR = SignalPredictor()
    return _PREDICTOR


def reset_predictor() -> None:
    global _PREDICTOR
    if _PREDICTOR is not None:
        _PREDICTOR.close()
    _PREDICTOR = None


__all__ = [
    "PredictorUnavailable",
    "SignalFeatures",
    "SignalPredictor",
    "get_predictor",
    "reset_predictor",
]

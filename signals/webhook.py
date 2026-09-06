"""Webhook entrypoint for TradingView Swing Reversal Pro signals."""

from __future__ import annotations

import asyncio
import hmac
import os
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
import structlog

from pipeline import circuit_breaker
from pipeline.metrics.signals import (
    ML_CONFIDENCE_HISTOGRAM,
    SIGNALS_RECEIVED_TOTAL,
    SIGNALS_VALIDATED_TOTAL,
)

from .drift_detector import detect_drift
from .ml_predictor import PredictorUnavailable, SignalFeatures, get_predictor
from .batch_predictor import BatchPredictorUnavailable, get_batch_predictor
from .telegram import TelegramConfigurationError, send_signal_alert
from .webhook_auth import validate_ip_trust

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/signals", tags=["signals"])

_WEBHOOK_BREAKER = "signals_webhook"
_RATE_LIMIT_WINDOW = float(os.getenv("SIGNALS_RATE_LIMIT_WINDOW", "60"))
_RATE_LIMIT: dict[str, float] = {}
_RATE_LOCK = asyncio.Lock()


class SignalPayload(BaseModel):
    type: str = Field(alias="type", min_length=1, max_length=32)
    symbol: str = Field(min_length=1, max_length=30)
    price: float = Field(gt=0)
    rsi: float = Field(ge=0, le=100)
    volume_ratio: float = Field(gt=0)
    fvg: bool
    divergence: bool
    mtf: bool
    timestamp: datetime

    class Config:
        extra = "forbid"
        allow_population_by_field_name = True

    @field_validator("symbol")
    def _upper_symbol(cls, value: str) -> str:
        return value.upper()

    def to_features(self) -> SignalFeatures:
        return SignalFeatures(
            price=self.price,
            rsi=self.rsi,
            volume_ratio=self.volume_ratio,
            fvg=int(self.fvg),
            divergence=int(self.divergence),
            mtf=int(self.mtf),
        )

    def as_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


def _get_client_ip(request: Request) -> str:
    client = request.client
    if client and client.host:
        return client.host
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return "unknown"


async def _enforce_rate_limit(ip: str) -> None:
    now = time.monotonic()
    async with _RATE_LOCK:
        last_hit = _RATE_LIMIT.get(ip)
        if last_hit is not None and (now - last_hit) < _RATE_LIMIT_WINDOW:
            SIGNALS_RECEIVED_TOTAL.labels(status="rate_limited").inc()
            raise HTTPException(status_code=429, detail="rate limit")
        _RATE_LIMIT[ip] = now


def _validate_secret(request: Request) -> None:
    expected = os.getenv("TRADINGVIEW_WEBHOOK_TOKEN", "").strip()
    if not expected:
        return
    provided = request.headers.get("X-Webhook-Token", "").strip()
    if not provided or not hmac.compare_digest(expected, provided):
        SIGNALS_RECEIVED_TOTAL.labels(status="forbidden").inc()
        raise HTTPException(status_code=403, detail="invalid token")


@router.post("/webhook")
async def receive_signal(payload: SignalPayload, request: Request) -> JSONResponse:
    _validate_secret(request)
    ip = _get_client_ip(request)
    validate_ip_trust(ip)
    await _enforce_rate_limit(ip)

    if circuit_breaker.should_skip(_WEBHOOK_BREAKER):
        logger.warning("signals_breaker_open", signal_type=payload.type, symbol=payload.symbol)
        SIGNALS_RECEIVED_TOTAL.labels(status="breaker_open").inc()
        raise HTTPException(status_code=503, detail="signals temporarily disabled")

    predictor = get_predictor()
    features = payload.to_features()

    # Try batch prediction first for better throughput
    confidence = None
    try:
        batch_predictor = await get_batch_predictor()
        confidence = await batch_predictor.predict(features)
        logger.debug("batch_prediction_used", symbol=payload.symbol, confidence=confidence)
    except (BatchPredictorUnavailable, TimeoutError) as exc:
        logger.debug("batch_prediction_fallback", symbol=payload.symbol, error=str(exc))
        # Fallback to single prediction
        try:
            confidence = predictor.predict(features)
        except PredictorUnavailable:
            circuit_breaker.record_failure(_WEBHOOK_BREAKER)
            logger.warning(
                "signals_ml_unavailable",
                signal_type=payload.type,
                symbol=payload.symbol,
            )
            SIGNALS_RECEIVED_TOTAL.labels(status="queued").inc()
            return JSONResponse(
                status_code=202,
                content={
                    "status": "queued",
                    "detail": "model unavailable, signal stored",
                    "symbol": payload.symbol,
                },
            )

    # Check for drift
    drift_detected = await detect_drift(features)
    if drift_detected:
        logger.warning("drift_detected_in_signal", symbol=payload.symbol, confidence=confidence)

    circuit_breaker.record_success(_WEBHOOK_BREAKER)
    threshold = _confidence_threshold()
    decision = "validated" if confidence >= threshold else "rejected"
    SIGNALS_VALIDATED_TOTAL.labels(decision=decision).inc()
    ML_CONFIDENCE_HISTOGRAM.labels(decision=decision).observe(confidence)

    logger.info(
        "signals_processed",
        signal_type=payload.type,
        symbol=payload.symbol,
        confidence=confidence,
        decision=decision,
    )

    if decision == "validated":
        try:
            await send_signal_alert(payload.as_payload(), confidence)
        except TelegramConfigurationError as exc:
            logger.error(
                "signals_telegram_configuration",
                error=str(exc),
                symbol=payload.symbol,
            )
            SIGNALS_RECEIVED_TOTAL.labels(status="telegram_misconfigured").inc()
            raise HTTPException(status_code=500, detail="telegram misconfigured") from exc
        except Exception as exc:
            logger.error(
                "signals_telegram_failed",
                error=str(exc),
                symbol=payload.symbol,
            )
            SIGNALS_RECEIVED_TOTAL.labels(status="delivery_failed").inc()
            raise HTTPException(status_code=502, detail="telegram delivery failed") from exc

        SIGNALS_RECEIVED_TOTAL.labels(status="delivered").inc()
    else:
        SIGNALS_RECEIVED_TOTAL.labels(status="rejected").inc()

    return JSONResponse(
        {
            "status": decision,
            "confidence": round(confidence, 4),
            "threshold": threshold,
            "symbol": payload.symbol,
            "type": payload.type,
        }
    )


@router.get("/health", tags=["signals"])
async def signals_health() -> dict[str, Any]:
    predictor = get_predictor()

    # Get batch predictor metrics if available
    batch_metrics = {}
    try:
        batch_predictor = await get_batch_predictor()
        batch_metrics = {
            "batch_running": batch_predictor.is_running,
            "batch_queue_size": batch_predictor.queue_size,
            "batch_cache_hit_rate": round(batch_predictor.cache_hit_rate, 3),
            "batch_avg_processing_time_ms": round(batch_predictor.avg_processing_time, 2),
        }
    except (BatchPredictorUnavailable, TimeoutError):
        batch_metrics = {"batch_available": False}

    return {
        "status": "ok" if predictor.model_loaded else "degraded",
        "model_loaded": predictor.model_loaded,
        "backlog_size": predictor.backlog_size(),
        "last_error": predictor.last_error,
        **batch_metrics,
    }


def _confidence_threshold() -> float:
    try:
        return float(os.getenv("SIGNALS_CONFIDENCE_THRESHOLD", "0.85"))
    except Exception:
        return 0.85


__all__ = ["router", "SignalPayload"]

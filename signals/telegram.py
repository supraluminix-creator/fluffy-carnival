"""Telegram notifications for validated swing reversal signals."""

from __future__ import annotations

import os
from typing import Any, cast

import httpx
import structlog

from pipeline import circuit_breaker
from pipeline.http_wrappers import async_http_post_json_retry, AsyncHttpClient

logger = structlog.get_logger(__name__)

_TELEGRAM_BREAKER = "signals_telegram"


class TelegramConfigurationError(RuntimeError):
    """Raised when Telegram configuration is missing or invalid."""


async def send_signal_alert(payload: dict[str, Any], confidence: float) -> None:
    """Send a formatted alert to the configured Telegram chat.

    Args:
        payload: Raw webhook payload dictionary.
        confidence: ML confidence score in the [0,1] range.
    """

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise TelegramConfigurationError("Telegram configuration missing")

    if circuit_breaker.should_skip(_TELEGRAM_BREAKER):
        logger.warning("telegram_breaker_open", symbol=payload.get("symbol"))
        raise RuntimeError("telegram breaker open")

    message = _build_message(payload=payload, confidence=confidence)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        try:
            await async_http_post_json_retry(cast(AsyncHttpClient, client), url, json=data, backoff_base=0.5, retries=3)
        except Exception as exc:
            circuit_breaker.record_failure(_TELEGRAM_BREAKER)
            logger.error("telegram_alert_failed", error=str(exc), symbol=payload.get("symbol"))
            raise
        else:
            circuit_breaker.record_success(_TELEGRAM_BREAKER)
            logger.info("telegram_alert_sent", symbol=payload.get("symbol"), confidence=confidence)


def _build_message(*, payload: dict[str, Any], confidence: float) -> str:
    symbol = payload.get("symbol", "?")
    signal_type = payload.get("type", "signal")
    price = payload.get("price")
    rsi = payload.get("rsi")
    volume_ratio = payload.get("volume_ratio")
    divergence = payload.get("divergence")
    fvg = payload.get("fvg")
    mtf = payload.get("mtf")
    timestamp = payload.get("timestamp")
    confidence_pct = round(confidence * 100, 2)

    return (
        f"*Swing Reversal Pro*\n"
        f"Signal: `{signal_type}`\n"
        f"Symbol: `{symbol}`\n"
        f"Price: {price}\n"
        f"RSI: {rsi} | Volume ratio: {volume_ratio}\n"
        f"FVG: {bool(fvg)} | Divergence: {bool(divergence)} | MTF: {bool(mtf)}\n"
        f"Timestamp: {timestamp}\n"
        f"Confidence: {confidence_pct:.2f}%"
    )


__all__ = ["send_signal_alert", "TelegramConfigurationError"]

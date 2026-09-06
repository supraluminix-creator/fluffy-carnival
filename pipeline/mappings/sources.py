from __future__ import annotations

import asyncio
from typing import Any

import structlog

from pipeline.http import async_fetch_json

log = structlog.get_logger()


_COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"
_BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
_BYBIT_LINEAR_URL = "https://api.bybit.com/v5/market/instruments-info"


async def fetch_coingecko_coins_list(*, timeout: float = 20.0) -> list[dict[str, Any]]:
    """Return the raw CoinGecko coins list (id, symbol, name).

    The endpoint returns lower-case symbols. We keep the payload minimal to
    avoid surprising callers; higher-level helpers transform it.
    """

    params = {"include_platform": "false"}
    try:
        data = await async_fetch_json(_COINGECKO_LIST_URL, params=params, timeout=timeout)
    except Exception as exc:  # pragma: no cover - network handled in caller tests
        log.warning("coingecko_list_fetch_failed", error=str(exc))
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    log.warning("coingecko_list_unexpected_payload", payload_type=type(data).__name__)
    return []


async def fetch_binance_symbols(*, timeout: float = 15.0) -> list[dict[str, Any]]:
    """Return Binance spot symbols metadata (base/quote assets)."""

    try:
        data = await async_fetch_json(_BINANCE_EXCHANGE_INFO_URL, timeout=timeout)
    except Exception as exc:  # pragma: no cover - network handled in caller tests
        log.warning("binance_exchange_info_failed", error=str(exc))
        return []
    symbols = data.get("symbols") if isinstance(data, dict) else None
    return [item for item in symbols or [] if isinstance(item, dict)]


async def fetch_bybit_linear_symbols(*, timeout: float = 15.0, category: str = "linear") -> list[dict[str, Any]]:
    """Return Bybit linear instruments (USDT-margined perpetuals by default)."""

    params = {"category": category}
    cursor: str | None = None
    out: list[dict[str, Any]] = []
    while True:
        if cursor:
            params["cursor"] = cursor
        try:
            data = await async_fetch_json(_BYBIT_LINEAR_URL, params=params, timeout=timeout)
        except Exception as exc:  # pragma: no cover - network handled in caller tests
            log.warning("bybit_linear_fetch_failed", error=str(exc), cursor=cursor)
            break
        if not isinstance(data, dict):
            log.warning("bybit_linear_unexpected_payload", payload_type=type(data).__name__)
            break
        result = data.get("result")
        if not isinstance(result, dict):
            break
        list_items = result.get("list")
        if isinstance(list_items, list):
            out.extend(item for item in list_items if isinstance(item, dict))
        cursor = result.get("nextPageCursor") if isinstance(result.get("nextPageCursor"), str) else None
        if not cursor:
            break
        await asyncio.sleep(0.2)
    return out

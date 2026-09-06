"""High-level snapshot collectors for prompt generation and reports.

This module bundles lightweight REST fetchers (CoinGecko, Bybit, etc.) so that
analysis tooling can gather a consistent view of the market without relying on
previous exports. Everything is async-friendly and resilient: each fetch
returns `None` on failure while logging context for observability.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import json
import math
import os
import sqlite3
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import structlog

from pipeline.assets import AssetInfo, describe_assets
from pipeline.collectors.derivatives import fetch_bybit_long_short_ratio
from pipeline.collectors.market import fetch_market
from pipeline.collectors.orderbook import fetch_orderbook_summary
from pipeline.http import async_fetch_json
from pipeline.storage.sqlite_adapter import get_default_db_path

logger = structlog.get_logger(__name__)

_COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
_BYBIT_OI_URL = "https://api.bybit.com/v5/market/open-interest"
_BYBIT_FUNDING_URL = "https://api.bybit.com/v5/market/funding/history"
_BYBIT_LIQUIDATION_URL = "https://api.bybit.com/v5/market/liquidation"
_COINGECKO_MARKET_THROTTLE = float(os.getenv("COINGECKO_MARKET_THROTTLE_MS", "250")) / 1000.0
_LIQUIDATIONS_DB_PATH = os.getenv("LIQUIDATIONS_DB_PATH", get_default_db_path())
_METRICS_JSON_PATH = Path(os.getenv("METRICS_JSON_PATH", "data/metrics.json"))
_METRICS_CSV_PATH = Path(os.getenv("METRICS_CSV_PATH", "data/metrics.csv"))
_METRICS_DB_PATH = Path(os.getenv("METRICS_DB_PATH", "data/metrics.db"))
_ALLOWED_OI_INTERVALS = {"5min", "15min", "30min", "1h", "4h", "1d"}
_DEFAULT_OI_INTERVAL = "15min"
_BYBIT_OI_INTERVAL = os.getenv("BYBIT_OI_INTERVAL", _DEFAULT_OI_INTERVAL).lower()
if _BYBIT_OI_INTERVAL not in _ALLOWED_OI_INTERVALS:
    _BYBIT_OI_INTERVAL = _DEFAULT_OI_INTERVAL


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _load_metrics_archive() -> dict[str, dict[str, float]]:
    archive: dict[str, dict[str, float]] = {}

    def store(symbol: Any, metric: Any, value: Any) -> None:
        if symbol is None or metric is None:
            return
        symbol_norm = str(symbol).strip().upper()
        if not symbol_norm:
            return
        val = _to_float(value)
        if val is None:
            return
        archive.setdefault(symbol_norm, {})[str(metric)] = val

    if _METRICS_JSON_PATH.exists():
        with contextlib.suppress(Exception):
            data = json.loads(_METRICS_JSON_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for row in data:
                    if isinstance(row, dict):
                        store(row.get("symbol"), row.get("metric"), row.get("value"))

    if _METRICS_CSV_PATH.exists():
        try:
            with _METRICS_CSV_PATH.open("r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    store(row.get("symbol"), row.get("metric"), row.get("value"))
        except Exception:
            pass

    if _METRICS_DB_PATH.exists():
        with contextlib.suppress(Exception):
            conn = sqlite3.connect(str(_METRICS_DB_PATH))
            try:
                cur = conn.cursor()
                cur.execute("SELECT metric, symbol, value FROM metrics")
                rows = cur.fetchall()
                for metric, symbol, value in rows:
                    store(symbol, metric, value)
            finally:
                with contextlib.suppress(Exception):
                    conn.close()

    return archive


@dataclass(slots=True)
class AssetSnapshot:
    asset: str
    price: float | None = None
    price_change_24h_pct: float | None = None
    market_cap_usd: float | None = None
    volume_24h_usd: float | None = None
    volume_change_24h_pct: float | None = None
    funding_rate: float | None = None
    oi_usd: float | None = None
    oi_change_1h_usd: float | None = None
    oi_change_1h_pct: float | None = None
    oi_change_24h_usd: float | None = None
    oi_change_24h_pct: float | None = None
    liquidations_total_usd: float | None = None
    liquidations_long_usd: float | None = None
    liquidations_short_usd: float | None = None
    orderbook: dict[str, Any] | None = None
    long_short_ratio_long_pct: float | None = None
    long_short_ratio_short_pct: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out = {
            "asset": self.asset,
            "price": self.price,
            "price_change_24h_pct": self.price_change_24h_pct,
            "market_cap_usd": self.market_cap_usd,
            "volume_24h_usd": self.volume_24h_usd,
            "volume_change_24h_pct": self.volume_change_24h_pct,
            "funding_rate": self.funding_rate,
            "oi_usd": self.oi_usd,
            "oi_change_1h_usd": self.oi_change_1h_usd,
            "oi_change_1h_pct": self.oi_change_1h_pct,
            "oi_change_24h_usd": self.oi_change_24h_usd,
            "oi_change_24h_pct": self.oi_change_24h_pct,
            "liquidations_24h_total_usd": self.liquidations_total_usd,
            "liquidations_24h_long_usd": self.liquidations_long_usd,
            "liquidations_24h_short_usd": self.liquidations_short_usd,
            "long_short_ratio_long_pct": self.long_short_ratio_long_pct,
            "long_short_ratio_short_pct": self.long_short_ratio_short_pct,
        }
        if self.orderbook is not None:
            out["orderbook"] = self.orderbook
        if self.extras:
            out["extras"] = self.extras
        return out


def _apply_archived_metrics(snapshot: AssetSnapshot, asset: str, archived: dict[str, float] | None) -> None:
    if not isinstance(archived, dict) or not archived:
        return
    applied: list[str] = []

    price = archived.get("price_usd")
    if snapshot.price is None and price is not None:
        snapshot.price = price
        applied.append("price")

    price_delta = archived.get("change_24h_pct")
    if snapshot.price_change_24h_pct is None and price_delta is not None:
        snapshot.price_change_24h_pct = price_delta
        applied.append("price_change_24h_pct")

    funding_rate = archived.get("funding_rate")
    if snapshot.funding_rate is None and funding_rate is not None:
        snapshot.funding_rate = funding_rate
        applied.append("funding_rate")

    if not applied:
        return

    fallbacks = snapshot.extras.setdefault("fallbacks", [])
    if "metrics_archive" not in fallbacks:
        fallbacks.append("metrics_archive")
    logger.info("snapshot_archive_fallback", asset=asset, fields=applied)


async def _fetch_coingecko_metrics(asset_info: Sequence[AssetInfo]) -> dict[str, dict[str, float | None]]:
    ids: list[str] = []
    id_to_asset: dict[str, str] = {}
    for info in asset_info:
        if not info.coingecko_id:
            continue
        ids.append(info.coingecko_id)
        id_to_asset[info.coingecko_id] = info.asset
    if not ids:
        return {}
    params = {
        "ids": ",".join(ids),
        "vs_currencies": "usd",
        "include_24hr_change": "true",
        "include_market_cap": "true",
        "include_24hr_vol": "true",
    }
    try:
        data = await async_fetch_json(_COINGECKO_SIMPLE_PRICE_URL, params=params, timeout=10)
    except Exception as exc:  # pragma: no cover - network errors already logged upstream
        logger.warning("coingecko_fetch_failed", asset_ids=list(ids), error=str(exc))
        data = None
    metrics: dict[str, dict[str, float | None]] = {}
    for cg_id, payload in (data or {}).items():
        asset = id_to_asset.get(cg_id)
        if not asset or not isinstance(payload, dict):
            continue
        metrics[asset] = {
            "price": _to_float(payload.get("usd")),
            "price_change_pct": _to_float(payload.get("usd_24h_change")),
            "market_cap": _to_float(payload.get("usd_market_cap")),
            "volume_24h": _to_float(payload.get("usd_24h_vol")),
        }

    pending: list[AssetInfo] = []
    for info in asset_info:
        if not info.coingecko_id:
            continue
        entry = metrics.get(info.asset, {})
        needs_advanced = (
            entry.get("market_cap") is None
            or entry.get("volume_24h") is None
            or entry.get("volume_change_pct") is None
            or "dominance_pct" not in entry
        )
        if needs_advanced:
            pending.append(info)

    for idx, info in enumerate(pending):
        try:
            payload = await asyncio.to_thread(fetch_market, info.coingecko_id)
        except Exception as exc:  # pragma: no cover - fetch_market already logs
            logger.warning("market_metrics_fetch_failed", asset=info.asset, error=str(exc))
            continue
        if not isinstance(payload, dict):
            continue
        entry = metrics.setdefault(info.asset, {})
        price = _to_float(payload.get("price"))
        if entry.get("price") is None and price is not None:
            entry["price"] = price
        price_pct = _to_float(payload.get("price_change_pct_24h"))
        if entry.get("price_change_pct") is None and price_pct is not None:
            entry["price_change_pct"] = price_pct
        volume = _to_float(payload.get("volume_24h"))
        if entry.get("volume_24h") is None and volume is not None:
            entry["volume_24h"] = volume
        market_cap = _to_float(payload.get("marketcap"))
        if entry.get("market_cap") is None and market_cap is not None:
            entry["market_cap"] = market_cap
        volume_change = _to_float(payload.get("volume_change_pct_24h"))
        if volume_change is not None:
            entry["volume_change_pct"] = volume_change
        dominance = _to_float(payload.get("dominance"))
        if dominance is not None:
            entry["dominance_pct"] = dominance
        if _COINGECKO_MARKET_THROTTLE > 0 and idx < len(pending) - 1:
            await asyncio.sleep(_COINGECKO_MARKET_THROTTLE)

    archived_metrics = _load_metrics_archive()
    for info in asset_info:
        archived_entry = archived_metrics.get(info.asset)
        if not archived_entry:
            continue
        entry = metrics.setdefault(info.asset, {})
        if entry.get("price") is None and archived_entry.get("price_usd") is not None:
            entry["price"] = archived_entry.get("price_usd")
        if entry.get("price_change_pct") is None and archived_entry.get("change_24h_pct") is not None:
            entry["price_change_pct"] = archived_entry.get("change_24h_pct")
        if entry.get("funding_rate") is None and archived_entry.get("funding_rate") is not None:
            entry["funding_rate"] = archived_entry.get("funding_rate")
    return metrics


async def _fetch_bybit_open_interest_series(
    symbol: str,
    *,
    interval: str | None = None,
) -> list[tuple[int, float]]:
    resolved_interval = (interval or _BYBIT_OI_INTERVAL).lower()
    if resolved_interval not in _ALLOWED_OI_INTERVALS:
        resolved_interval = _DEFAULT_OI_INTERVAL
    params = {
        "category": "linear",
        "symbol": symbol.upper(),
        "intervalTime": resolved_interval,
    }
    data = await async_fetch_json(_BYBIT_OI_URL, params=params, timeout=10)
    entries = (data or {}).get("result", {}).get("list", [])
    series: list[tuple[int, float]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ts_raw = entry.get("timestamp") or entry.get("time")
        val_raw = entry.get("openInterest") or entry.get("openInterestValue")
        ts = _to_float(ts_raw)
        val = _to_float(val_raw)
        if ts is None or val is None:
            continue
        series.append((int(ts), float(val)))
    series.sort(key=lambda item: item[0])
    return series


def _compute_delta(series: Sequence[tuple[int, float]], lookback_seconds: int) -> tuple[float | None, float | None]:
    if not series:
        return (None, None)
    latest_ts, latest_val = series[-1]
    threshold = latest_ts - lookback_seconds * 1000
    previous_val: float | None = None
    for ts, val in reversed(series):
        if ts <= threshold:
            previous_val = val
            break
    if previous_val is None:
        return (None, None)
    abs_delta = latest_val - previous_val
    if math.isclose(previous_val, 0.0, abs_tol=1e-9):
        pct_delta: float | None = None
    else:
        pct_delta = (abs_delta / previous_val) * 100
    return (abs_delta, pct_delta)


async def _fetch_funding_rate(symbol: str) -> float | None:
    params = {
        "category": "linear",
        "symbol": symbol.upper(),
        "limit": 1,
    }
    try:
        data = await async_fetch_json(_BYBIT_FUNDING_URL, params=params, timeout=10)
    except Exception as exc:  # pragma: no cover
        logger.warning("funding_fetch_failed", symbol=symbol, error=str(exc))
        return None
    items = (data or {}).get("result", {}).get("list", [])
    if not items:
        return None
    last = items[-1]
    if not isinstance(last, dict):
        return None
    return _to_float(last.get("fundingRate"))


async def _fetch_liquidations(symbol: str, *, hours: int) -> dict[str, Any] | None:
    end_time = _now_ms()
    start_time = end_time - hours * 3600 * 1000
    cursor: str | None = None
    total = 0.0
    longs = 0.0
    shorts = 0.0
    page = 0
    rest_failed = False
    while True:
        params = {
            "category": "linear",
            "symbol": symbol.upper(),
            "startTime": start_time,
            "endTime": end_time,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        try:
            data = await async_fetch_json(_BYBIT_LIQUIDATION_URL, params=params, timeout=10)
        except Exception as exc:  # pragma: no cover
            logger.warning("liquidation_fetch_failed", symbol=symbol, page=page, error=str(exc))
            rest_failed = True
            break
        result = (data or {}).get("result", {})
        items = result.get("list") or []
        if not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            ts_raw = item.get("time") or item.get("updatedTime") or item.get("timestamp")
            ts = _to_float(ts_raw)
            if ts is not None and ts < start_time:
                continue
            qty = _to_float(item.get("qty") or item.get("qtySize"))
            price = _to_float(item.get("price"))
            if qty is None or price is None:
                continue
            notional = float(qty) * float(price)
            total += notional
            side = str(item.get("side") or "").lower()
            if side in {"buy", "long"}:
                longs += notional
            elif side in {"sell", "short"}:
                shorts += notional
        cursor = result.get("nextPageCursor")
        page += 1
        if not cursor or page >= 10:
            break
    if total == 0.0 and longs == 0.0 and shorts == 0.0:
        fallback = _fallback_liquidations_from_db(symbol, start_time, end_time)
        if fallback is not None:
            fallback.setdefault("source", "archive")
            if rest_failed:
                fallback["rest_error"] = True
        return fallback
    payload: dict[str, Any] = {
        "total": total,
        "longs": longs or None,
        "shorts": shorts or None,
        "source": "bybit_rest",
        "window_start_ms": start_time,
        "window_end_ms": end_time,
    }
    if rest_failed:
        payload["rest_error"] = True
    return payload


def _fallback_liquidations_from_db(symbol: str, start_ms: int, end_ms: int) -> dict[str, Any] | None:
    path = Path(_LIQUIDATIONS_DB_PATH)
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(str(path))
    except Exception:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bybit_liquidations'")
        row = cur.fetchone()
        if not row:
            return None
        table_name = str(row[0])
        cur.execute(f"PRAGMA table_info({table_name})")
        schema = {str(col[1]).lower(): str(col[1]) for col in cur.fetchall()}

        def resolve(*candidates: str) -> str | None:
            for candidate in candidates:
                hit = schema.get(candidate.lower())
                if hit:
                    return hit
            return None

        time_col = resolve("time", "timestamp", "ts")
        if not time_col:
            return None
        symbol_col = resolve("symbol", "pair")
        side_col = resolve("side", "position_side")
        qty_usd_col = resolve("qty_usd", "notional_usd", "value_usd")
        qty_col = resolve("qty", "size", "qty_size", "quantity")
        price_col = resolve("price", "fill_price", "execution_price")
        if not qty_usd_col and (not qty_col or not price_col):
            return None

        def q(identifier: str) -> str:
            return f'"{identifier}"'

        if qty_usd_col:
            notional_expr = f"COALESCE(CAST({q(qty_usd_col)} AS REAL), 0.0)"
        else:
            notional_expr = (
                f"COALESCE(CAST({q(qty_col)} AS REAL), 0.0) * "
                f"COALESCE(CAST({q(price_col)} AS REAL), 0.0)"
            )

        if side_col:
            side_expr = f"UPPER({q(side_col)})"
            long_expr = f"SUM(CASE WHEN {side_expr} IN ('BUY','LONG') THEN {notional_expr} ELSE 0 END)"
            short_expr = f"SUM(CASE WHEN {side_expr} IN ('SELL','SHORT') THEN {notional_expr} ELSE 0 END)"
        else:
            long_expr = "NULL"
            short_expr = "NULL"

        base_query = (
            "SELECT "
            f"SUM({notional_expr}) AS total, "
            f"{long_expr} AS long_total, "
            f"{short_expr} AS short_total, "
            "COUNT(*) AS events "
            f"FROM {q(table_name)} "
            f"WHERE {q(time_col)} >= ? AND {q(time_col)} <= ?"
        )

        candidates = [symbol.upper()]
        if symbol.upper().endswith("USDT") or symbol.upper().endswith("USDC"):
            candidates.append(symbol.upper()[:-4])

        window_ms = max(end_ms - start_ms, 1)

        def aggregate(lower: int, upper: int) -> tuple[dict[str, Any] | None, int]:
            agg_total = 0.0
            agg_longs = 0.0
            agg_shorts = 0.0
            agg_events = 0
            saw_longs = False
            saw_shorts = False

            for candidate in candidates:
                params: list[Any] = [lower, upper]
                query = base_query
                if symbol_col and candidate:
                    query += f" AND {q(symbol_col)} = ?"
                    params.append(candidate)
                cur.execute(query, params)
                fetched = cur.fetchone()
                if not fetched:
                    continue
                total, long_total, short_total, events = fetched
                agg_total += float(total or 0.0)
                if long_total is not None:
                    agg_longs += float(long_total or 0.0)
                    saw_longs = True
                if short_total is not None:
                    agg_shorts += float(short_total or 0.0)
                    saw_shorts = True
                agg_events += int(events or 0)

            if agg_events == 0 and agg_total == 0.0 and not saw_longs and not saw_shorts:
                return (None, 0)

            payload: dict[str, Any] = {
                "total": agg_total or None,
                "longs": agg_longs if saw_longs else None,
                "shorts": agg_shorts if saw_shorts else None,
                "event_count": agg_events,
                "window_start_ms": lower,
                "window_end_ms": upper,
            }
            return (payload, agg_events)

        primary_data, events = aggregate(start_ms, end_ms)
        if primary_data is not None:
            return primary_data

        # No data in requested window; look for the freshest slice in archives.
        params_symbols: list[str] = []
        if symbol_col:
            params_symbols.extend(candidates)
        max_time: int | None = None
        if symbol_col and params_symbols:
            placeholders = ",".join("?" for _ in params_symbols)
            cur.execute(
                f"SELECT MAX({q(time_col)}) FROM {q(table_name)} WHERE {q(symbol_col)} IN ({placeholders})",
                params_symbols,
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                max_time = int(row[0])
        else:
            cur.execute(f"SELECT MAX({q(time_col)}) FROM {q(table_name)}")
            row = cur.fetchone()
            if row and row[0] is not None:
                max_time = int(row[0])

        if max_time is None:
            return None

        alt_end = max_time
        alt_start = max_time - window_ms
        alt_data, alt_events = aggregate(alt_start, alt_end)
        if alt_data is None:
            return None
        alt_data["stale"] = True
        alt_data.setdefault("event_count", alt_events)
        return alt_data
    except Exception:
        return None
    finally:
        with contextlib.suppress(Exception):
            conn.close()


async def _gather_single_asset(
    info: AssetInfo,
    *,
    hours: int,
    orderbook_depth: int,
    orderbook_top_n: int,
    price_metrics: dict[str, dict[str, float | None]],
    archived_metrics: dict[str, dict[str, float]],
) -> AssetSnapshot:
    snapshot = AssetSnapshot(asset=info.asset)
    metrics = price_metrics.get(info.asset, {})
    snapshot.price = metrics.get("price")
    snapshot.price_change_24h_pct = metrics.get("price_change_pct")
    snapshot.market_cap_usd = metrics.get("market_cap")
    snapshot.volume_24h_usd = metrics.get("volume_24h")
    snapshot.volume_change_24h_pct = metrics.get("volume_change_pct")
    funding_from_metrics = _to_float(metrics.get("funding_rate")) if metrics else None
    if funding_from_metrics is not None:
        snapshot.funding_rate = funding_from_metrics
    dominance = metrics.get("dominance_pct")
    if dominance is not None:
        snapshot.extras.setdefault("market", {})["dominance_pct"] = dominance

    perp_symbol = info.perp_symbol
    tasks = [
        _fetch_bybit_open_interest_series(perp_symbol),
        _fetch_funding_rate(perp_symbol),
        _fetch_liquidations(perp_symbol, hours=hours),
        fetch_orderbook_summary(perp_symbol, depth=orderbook_depth, top_n=orderbook_top_n),
        fetch_bybit_long_short_ratio(perp_symbol),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    oi_series = results[0]
    if isinstance(oi_series, Exception):
        logger.warning("open_interest_fetch_failed", asset=info.asset, error=str(oi_series))
        oi_series = []
    if isinstance(oi_series, Sequence) and oi_series:
        snapshot.oi_usd = oi_series[-1][1]
        snapshot.oi_change_1h_usd, snapshot.oi_change_1h_pct = _compute_delta(oi_series, 3600)
        snapshot.oi_change_24h_usd, snapshot.oi_change_24h_pct = _compute_delta(oi_series, 86400)

    funding = results[1]
    if isinstance(funding, Exception):
        logger.warning("funding_fetch_failed_async", asset=info.asset, error=str(funding))
        funding = None
    snapshot.funding_rate = _to_float(funding)

    liq = results[2]
    if isinstance(liq, Exception):
        logger.warning("liquidations_fetch_failed_async", asset=info.asset, error=str(liq))
    elif isinstance(liq, dict):
        snapshot.liquidations_total_usd = liq.get("total")
        snapshot.liquidations_long_usd = liq.get("longs")
        snapshot.liquidations_short_usd = liq.get("shorts")
        meta_keys = {
            "source": liq.get("source"),
            "event_count": liq.get("event_count"),
            "window_start_ms": liq.get("window_start_ms"),
            "window_end_ms": liq.get("window_end_ms"),
            "stale": liq.get("stale"),
            "rest_error": liq.get("rest_error"),
        }
        if any(value is not None for value in meta_keys.values()):
            snapshot.extras.setdefault("liquidations", {}).update(
                {k: v for k, v in meta_keys.items() if v is not None}
            )

    orderbook = results[3]
    if isinstance(orderbook, Exception):
        logger.warning("orderbook_fetch_failed", asset=info.asset, error=str(orderbook))
    elif isinstance(orderbook, dict):
        snapshot.orderbook = orderbook

    lsr = results[4]
    if isinstance(lsr, Exception):
        logger.warning("long_short_ratio_fetch_failed", asset=info.asset, error=str(lsr))
    elif isinstance(lsr, dict):
        value = lsr.get("value") if isinstance(lsr.get("value"), dict) else {}
        if isinstance(value, dict):
            snapshot.long_short_ratio_long_pct = _to_float(value.get("buy_ratio"))
            snapshot.long_short_ratio_short_pct = _to_float(value.get("sell_ratio"))
            snapshot.extras.setdefault("long_short_ratio", value)

    archived_entry = archived_metrics.get(info.asset)
    _apply_archived_metrics(snapshot, info.asset, archived_entry)

    return snapshot


async def gather_snapshots(
    assets: Iterable[str],
    *,
    hours: int = 24,
    orderbook_depth: int = 50,
    orderbook_top_n: int = 10,
) -> dict[str, AssetSnapshot]:
    """Collect snapshots for each asset."""

    asset_info = describe_assets(assets)
    price_metrics = await _fetch_coingecko_metrics(asset_info)
    archived_metrics = _load_metrics_archive()

    snapshots: dict[str, AssetSnapshot] = {}
    tasks = [
        _gather_single_asset(
            info,
            hours=hours,
            orderbook_depth=orderbook_depth,
            orderbook_top_n=orderbook_top_n,
            price_metrics=price_metrics,
            archived_metrics=archived_metrics,
        )
        for info in asset_info
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for info, result in zip(asset_info, results, strict=False):
        if isinstance(result, Exception):
            logger.warning("snapshot_collect_failed", asset=info.asset, error=str(result))
            continue
        snapshots[info.asset] = cast(AssetSnapshot, result)
    return snapshots


__all__ = ["AssetSnapshot", "gather_snapshots"]

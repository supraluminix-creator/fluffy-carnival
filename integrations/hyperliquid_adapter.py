from __future__ import annotations

import json
import os
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from pipeline.http import async_post_json
from pipeline.metrics.whales import (
    WHALE_HYPERLIQUID_LAST_UPDATED,
    WHALE_HYPERLIQUID_POSITION_LEVERAGE,
    WHALE_HYPERLIQUID_POSITION_NOTIONAL,
)

log = structlog.get_logger()


@dataclass(slots=True)
class HyperliquidWatcher:
    """Single Hyperliquid trader to monitor."""

    address: str
    user_id: str | None = None

    def label(self) -> str:
        base = (self.user_id or self.address or "trader").strip()
        return base.lower()


@dataclass(slots=True)
class HyperliquidConfig:
    enabled: bool
    api_base: str
    timeout: float
    cache_ttl: int
    watchlist: list[HyperliquidWatcher]
    export_dir: Path
    min_notional_alert: float


FetchFunc = Callable[["HyperliquidConfig", HyperliquidWatcher], Awaitable[Any]]

_PREVIOUS_POSITION_KEYS: set[tuple[str, str, str]] = set()


def _parse_watchlist(raw: str | None) -> list[HyperliquidWatcher]:
    if not raw:
        return []
    watchers: list[HyperliquidWatcher] = []
    for chunk in raw.replace("\n", ",").split(","):
        part = chunk.strip()
        if not part:
            continue
        if ":" in part:
            address, user_id = part.split(":", 1)
            watchers.append(HyperliquidWatcher(address=address.strip().lower(), user_id=user_id.strip() or None))
        else:
            watchers.append(HyperliquidWatcher(address=part.strip().lower(), user_id=None))
    return watchers


def load_config() -> HyperliquidConfig:
    enabled = os.getenv("HYPERLIQUID_ENABLED", "0") in {"1", "true", "yes", "on"}
    api_base = os.getenv("HYPERLIQUID_API_BASE", "https://api.hyperliquid.xyz/info").strip()
    timeout = float(os.getenv("HYPERLIQUID_TIMEOUT", "10"))
    cache_ttl = int(os.getenv("HYPERLIQUID_CACHE_TTL", "300"))
    export_dir = Path(os.getenv("HYPERLIQUID_EXPORT_DIR", "exports/whales")).resolve()
    min_notional_alert = float(os.getenv("HYPERLIQUID_ALERT_NOTIONAL_USD", "10000000"))

    watchlist = _parse_watchlist(os.getenv("HYPERLIQUID_WATCHLIST"))
    if not watchlist:
        # Fallback: reuse insider whale addresses if supplied (address only)
        watchlist = [
            HyperliquidWatcher(address=addr)
            for addr in _parse_addresses(os.getenv("INSIDER_WHALE_ADDRESSES"))
        ]

    return HyperliquidConfig(
        enabled=enabled,
        api_base=api_base,
        timeout=timeout,
        cache_ttl=cache_ttl,
        watchlist=watchlist,
        export_dir=export_dir,
        min_notional_alert=min_notional_alert,
    )


def _parse_addresses(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        part = chunk.strip().lower()
        if part:
            out.append(part)
    return out


async def fetch_positions(
    cfg: HyperliquidConfig,
    *,
    fetcher: FetchFunc | None = None,
    now_ts: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch Hyperliquid trader positions and normalize into pipeline records."""
    if not cfg.enabled:
        log.info("hyperliquid_disabled")
        return []
    if not cfg.watchlist:
        log.info("hyperliquid_empty_watchlist")
        return []
    fetch = fetcher or _default_fetcher
    timestamp = now_ts or int(time.time())
    all_records: list[dict[str, Any]] = []
    metric_keys: set[tuple[str, str, str]] = set()

    for watcher in cfg.watchlist:
        try:
            payload = await fetch(cfg, watcher)
        except Exception as exc:  # pragma: no cover - defensive logging
            log.warning("hyperliquid_fetch_exception", watcher=watcher.label(), error=str(exc))
            continue
        if not isinstance(payload, dict):
            log.info("hyperliquid_fetch_empty", watcher=watcher.label())
            continue
        positions = _normalize_positions(payload)
        summary = _extract_summary(payload)
        snapshot = {
            "timestamp": timestamp,
            "watcher": watcher.label(),
            "address": watcher.address,
            "user_id": watcher.user_id,
            "positions": positions,
            "summary": summary,
        }
        write_export(snapshot, cfg=cfg, watcher=watcher)

        for pos in positions:
            symbol = pos["symbol"]
            side = pos["side"]
            trader_label = watcher.label()
            metric_key = (trader_label, symbol, side)
            metric_keys.add(metric_key)
            WHALE_HYPERLIQUID_POSITION_NOTIONAL.labels(trader=trader_label, symbol=symbol, side=side).set(
                pos["notional_usd"]
            )
            WHALE_HYPERLIQUID_POSITION_LEVERAGE.labels(trader=trader_label, symbol=symbol, side=side).set(
                pos["leverage"]
            )
            record = {
                "timestamp": timestamp,
                "chain": "hyperliquid",
                "trader": trader_label,
                "symbol": symbol,
                "metric_name": "hl_position_notional_usd",
                "value": pos["notional_usd"],
                "source": "hyperliquid",
                "metadata": {
                    "side": side,
                    "leverage": pos["leverage"],
                    "entry_price": pos["entry_price"],
                    "pnl_unrealized": pos["unrealized_pnl"],
                    "size": pos["size"],
                },
            }
            all_records.append(record)
            if pos["leverage"]:
                all_records.append(
                    {
                        "timestamp": timestamp,
                        "chain": "hyperliquid",
                        "trader": trader_label,
                        "symbol": symbol,
                        "metric_name": "hl_position_leverage",
                        "value": pos["leverage"],
                        "source": "hyperliquid",
                        "metadata": {
                            "side": side,
                            "notional_usd": pos["notional_usd"],
                        },
                    }
                )
        if summary:
            pnl = summary.get("total_unrealized_pnl")
            if pnl is not None:
                all_records.append(
                    {
                        "timestamp": timestamp,
                        "chain": "hyperliquid",
                        "trader": watcher.label(),
                        "metric_name": "hl_total_unrealized_pnl",
                        "value": pnl,
                        "source": "hyperliquid",
                        "metadata": {
                            "total_notional": summary.get("total_notional"),
                            "positions": len(positions),
                        },
                    }
                )
        WHALE_HYPERLIQUID_LAST_UPDATED.labels(trader=watcher.label()).set(float(timestamp))

    _cleanup_metrics(metric_keys)
    return all_records


async def _default_fetcher(cfg: HyperliquidConfig, watcher: HyperliquidWatcher) -> Any:
    identifiers: list[Any] = []
    if watcher.user_id:
        identifiers.extend([
            {"type": "userState", "user": watcher.user_id},
            {"type": "userState", "user": {"userId": watcher.user_id}},
        ])
    if watcher.address:
        addr = watcher.address.lower()
        identifiers.extend([
            {"type": "userState", "user": addr},
            {"type": "userState", "user": {"address": addr}},
            {"type": "clearinghouseState", "user": {"address": addr}},
        ])
    if not identifiers:
        raise ValueError("Hyperliquid watcher missing identifier")

    last_error: Exception | None = None
    for body in identifiers:
        try:
            data = await async_post_json(cfg.api_base, json=body, timeout=cfg.timeout)
        except Exception as exc:  # pragma: no cover - log and continue
            last_error = exc
            log.debug("hyperliquid_post_failed", watcher=watcher.label(), error=str(exc))
            continue
        if isinstance(data, dict) and data:
            return data
    if last_error:
        raise last_error
    return {}


def _normalize_positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_positions: Sequence[Any] = ()
    if isinstance(payload.get("assetPositions"), Sequence):
        raw_positions = payload.get("assetPositions") or ()
    elif isinstance(payload.get("positions"), Sequence):
        raw_positions = payload.get("positions") or ()

    normalized: list[dict[str, Any]] = []
    for raw in raw_positions:
        if not isinstance(raw, dict):
            continue
        symbol = _as_symbol(raw)
        side = str(raw.get("side") or raw.get("positionSide") or raw.get("direction") or "flat").lower()
        leverage = _as_float(raw.get("leverage") or raw.get("positionLeverage"))
        notional = _as_float(
            raw.get("positionValue")
            or raw.get("usdValue")
            or raw.get("positionNotional")
            or raw.get("notional")
            or raw.get("sizeUsd")
        )
        size = _as_float(raw.get("size") or raw.get("baseSize") or raw.get("positionSize"))
        entry_price = _as_float(raw.get("entryPrice") or raw.get("avgEntry") or raw.get("entryPx"))
        pnl = _as_float(raw.get("unrealizedPnl") or raw.get("unrealisedPnl") or raw.get("pnl"))
        normalized.append(
            {
                "symbol": symbol,
                "side": side or "flat",
                "leverage": leverage,
                "notional_usd": notional,
                "size": size,
                "entry_price": entry_price,
                "unrealized_pnl": pnl,
            }
        )
    return normalized


def _as_symbol(raw: dict[str, Any]) -> str:
    for key in ("coin", "symbol", "asset", "pair"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value.upper()
    return "UNKNOWN"


def _as_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _extract_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    margin = payload.get("marginSummary")
    if isinstance(margin, dict):
        summary["total_notional"] = _as_float(margin.get("totalPosValue") or margin.get("totalPositionValue"))
        summary["total_unrealized_pnl"] = _as_float(margin.get("totalUnrealizedPnl"))
    pnl = payload.get("pnlAndFees")
    if isinstance(pnl, dict) and "openPnl" in pnl:
        summary["total_unrealized_pnl"] = _as_float(pnl.get("openPnl"))
    if "total_unrealized_pnl" not in summary:
        summary["total_unrealized_pnl"] = _as_float(payload.get("totalPnl") or payload.get("unrealizedPnl"))
    if "total_notional" not in summary:
        summary["total_notional"] = _as_float(payload.get("totalNotional"))
    return summary


def write_export(snapshot: dict[str, Any], *, cfg: HyperliquidConfig, watcher: HyperliquidWatcher) -> Path | None:
    safe = watcher.label().replace(":", "_")
    filename = f"hyperliquid_{safe or 'trader'}.json"
    path = cfg.export_dir / filename
    try:
        cfg.export_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    except Exception:  # pragma: no cover - no crash on export failure
        log.warning("hyperliquid_export_write_failed", path=str(path), watcher=watcher.label(), exc_info=True)
        return None


def _cleanup_metrics(current_keys: Iterable[tuple[str, str, str]]) -> None:
    global _PREVIOUS_POSITION_KEYS
    current = set(current_keys)
    stale = _PREVIOUS_POSITION_KEYS.difference(current)
    for trader, symbol, side in stale:
        try:
            WHALE_HYPERLIQUID_POSITION_NOTIONAL.remove(trader, symbol, side)
        except KeyError:
            pass
        except Exception:
            log.warning(
                "hyperliquid_metric_remove_failed",
                trader=trader,
                symbol=symbol,
                side=side,
                metric="notional",
                exc_info=True,
            )
        try:
            WHALE_HYPERLIQUID_POSITION_LEVERAGE.remove(trader, symbol, side)
        except KeyError:
            pass
        except Exception:
            log.warning(
                "hyperliquid_metric_remove_failed",
                trader=trader,
                symbol=symbol,
                side=side,
                metric="leverage",
                exc_info=True,
            )
    _PREVIOUS_POSITION_KEYS = current


def reset_hyperliquid_metric_state() -> None:
    """Testing helper to clear cached Hyperliquid metric label combinations."""
    global _PREVIOUS_POSITION_KEYS
    previous = list(_PREVIOUS_POSITION_KEYS)
    for trader, symbol, side in previous:
        try:
            WHALE_HYPERLIQUID_POSITION_NOTIONAL.remove(trader, symbol, side)
        except Exception:
            continue
        try:
            WHALE_HYPERLIQUID_POSITION_LEVERAGE.remove(trader, symbol, side)
        except Exception:
            continue
    _PREVIOUS_POSITION_KEYS = set()


__all__ = [
    "HyperliquidConfig",
    "HyperliquidWatcher",
    "fetch_positions",
    "load_config",
    "reset_hyperliquid_metric_state",
    "write_export",
]

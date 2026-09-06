from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

import structlog

from integrations.etherscan_adapter import collect_balance_records
from integrations.etherscan_adapter import load_config as load_etherscan_config
from integrations.hyperliquid_adapter import HyperliquidConfig, fetch_positions
from integrations.hyperliquid_adapter import load_config as load_hyperliquid_config
from pipeline.instrumentation import instrument_collector

log = structlog.get_logger()

_SNAPSHOT_FILENAME = "whale_insider_snapshot.json"


def write_snapshot(snapshot: dict[str, Any], *, cfg: HyperliquidConfig) -> Path | None:
    path = Path(cfg.export_dir) / _SNAPSHOT_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(
            "whale_insider_snapshot_written",
            path=str(path),
            records=len(snapshot.get("records") or []),
        )
        return path
    except Exception:  # pragma: no cover - snapshot persistence best-effort
        log.warning("whale_insider_snapshot_write_failed", path=str(path), exc_info=True)
        return None


def load_latest_snapshot(cfg: HyperliquidConfig | None = None) -> dict[str, Any] | None:
    cfg = cfg or load_hyperliquid_config()
    path = Path(cfg.export_dir) / _SNAPSHOT_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return cast(dict[str, Any], data)
        log.warning(
            "whale_insider_snapshot_unexpected_payload",
            path=str(path),
            payload_type=type(data).__name__,
        )
        return None
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        log.warning("whale_insider_snapshot_invalid_json", path=str(path))
    except Exception as exc:  # pragma: no cover - defensive logging
        log.warning("whale_insider_snapshot_read_failed", path=str(path), error=str(exc))
    return None


@instrument_collector("whale_insider")
async def fetch_whale_insider_snapshot() -> dict[str, Any] | None:
    """Combine on-chain and derivatives insights for monitored whales."""
    hl_cfg = load_hyperliquid_config()
    es_cfg = load_etherscan_config()

    records: list[dict[str, Any]] = []
    meta: dict[str, Any] = {
        "etherscan_watch_count": len(es_cfg.addresses),
        "hyperliquid_watch_count": len(hl_cfg.watchlist),
    }

    if es_cfg.enabled and es_cfg.addresses:
        eth_record_raw = await collect_balance_records(es_cfg)
        eth_record = cast(dict[str, Any] | None, eth_record_raw)
        if eth_record:
            records.append(eth_record)
    else:
        log.info("whale_insider_eth_disabled")

    if hl_cfg.enabled and hl_cfg.watchlist:
        hl_records_raw = await fetch_positions(hl_cfg)
        hl_records = cast(list[dict[str, Any]], hl_records_raw)
        records.extend(hl_records)
        meta["hyperliquid_records"] = len(hl_records)
    else:
        log.info("whale_insider_hyperliquid_disabled")

    if not records:
        log.info("whale_insider_no_records")
        return None

    snapshot = {
        "timestamp": int(time.time()),
        "records": records,
        "meta": {"records_count": len(records), **meta},
    }
    write_snapshot(snapshot, cfg=hl_cfg)
    return snapshot


__all__ = ["fetch_whale_insider_snapshot", "load_latest_snapshot", "write_snapshot"]

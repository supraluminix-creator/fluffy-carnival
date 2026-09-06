from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import structlog

from integrations.etherscan_adapter import EtherscanConfig, collect_balance_records, load_config
from pipeline.instrumentation import instrument_collector

log = structlog.get_logger()


@instrument_collector("whale_eth_balances")
async def fetch_eth_whale_balances() -> dict[str, Any] | None:
    cfg = load_config()
    if os.getenv("ENABLE_WHALE_BALANCES", "0") not in {"1", "true", "yes", "on"}:
        log.info("whale_balances_disabled_flag")
        return None
    if not cfg.enabled:
        log.info("whale_balances_config_disabled")
        return None
    if not cfg.addresses:
        log.warning("whale_balances_no_addresses_configured")
        return None
    record_raw = await collect_balance_records(cfg)
    record = cast(dict[str, Any] | None, record_raw)
    if record is None:
        log.warning("whale_balances_empty_result")
    return record


def load_latest_snapshot(cfg: EtherscanConfig | None = None) -> dict[str, Any] | None:
    """Load the latest whale balance JSON snapshot written by the collector."""
    cfg = cfg or load_config()
    path = Path(cfg.export_dir) / "etherscan_whale_balances.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return cast(dict[str, Any], data)
        log.warning("whale_balances_snapshot_unexpected_payload", path=str(path), payload_type=type(data).__name__)
        return None
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        log.warning("whale_balances_snapshot_invalid_json", path=str(path))
    except Exception as exc:  # pragma: no cover - defensive logging
        log.warning("whale_balances_snapshot_read_error", path=str(path), error=str(exc))
    return None


__all__ = ["fetch_eth_whale_balances", "load_latest_snapshot"]

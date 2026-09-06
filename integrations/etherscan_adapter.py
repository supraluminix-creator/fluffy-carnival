from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any

import structlog

from pipeline.http import async_fetch_json
from pipeline.metrics.whales import (
    WHALE_BALANCE_LAST_UPDATED,
    WHALE_BALANCE_PER_ADDRESS,
    WHALE_BALANCE_TOTAL,
)

log = structlog.get_logger()

_ETHERSCAN_API = "https://api.etherscan.io/api"
_WEI_IN_ETH = 10**18
_BALANCE_CHUNK = 20  # Max addresses per balancemulti call
_SOURCE = "etherscan"

_PREVIOUS_WHALE_ADDRESSES: set[str] = set()


@dataclass(slots=True)
class EtherscanConfig:
    enabled: bool
    api_key: str | None
    addresses: list[str]
    threshold_eth: float
    start_block: int
    end_block: int
    sleep_ms: int
    export_dir: Path


def _parse_addresses(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for part in raw.replace("\n", ",").split(","):
        addr = part.strip()
        if addr:
            out.append(addr.lower())
    return out


def load_config() -> EtherscanConfig:
    enabled = os.getenv("ETHERSCAN_ENABLED", "0") in {"1", "true", "yes", "on"}
    api_key = os.getenv("ETHERSCAN_API_KEY")
    addresses = _parse_addresses(os.getenv("ETHERSCAN_ADDRESSES"))
    try:
        threshold_eth = float(os.getenv("ETHERSCAN_THRESHOLD_ETH", "100"))
    except Exception:
        threshold_eth = 100.0
    start_block = int(os.getenv("ETHERSCAN_START_BLOCK", "0"))
    end_block = int(os.getenv("ETHERSCAN_END_BLOCK", "99999999"))
    sleep_ms = int(os.getenv("ETHERSCAN_SLEEP_MS", "200"))
    export_dir = Path(os.getenv("ETHERSCAN_EXPORT_DIR", "exports/onchain"))
    return EtherscanConfig(
        enabled=enabled,
        api_key=api_key,
        addresses=addresses,
        threshold_eth=threshold_eth,
        start_block=start_block,
        end_block=end_block,
        sleep_ms=sleep_ms,
        export_dir=export_dir,
    )


def _chunk_addresses(addresses: list[str], *, chunk_size: int = _BALANCE_CHUNK) -> list[list[str]]:
    return [addresses[i : i + chunk_size] for i in range(0, len(addresses), chunk_size)]


async def _fetch_balances(addresses: list[str], cfg: EtherscanConfig) -> list[dict[str, Any]]:
    if not addresses:
        return []
    params_base = {
        "module": "account",
        "action": "balancemulti",
        "tag": "latest",
    }
    if cfg.api_key:
        params_base["apikey"] = cfg.api_key
    results: list[dict[str, Any]] = []
    for chunk in _chunk_addresses(addresses):
        params = dict(params_base)
        params["address"] = ",".join(chunk)
        data = await async_fetch_json(_ETHERSCAN_API, params=params, timeout=15.0)
        if not isinstance(data, dict) or data.get("status") != "1":
            log.warning("etherscan_balance_error", message=data.get("message") if isinstance(data, dict) else None)
            continue
        chunk_result = data.get("result")
        if isinstance(chunk_result, list):
            results.extend(item for item in chunk_result if isinstance(item, dict))
    return results


async def _fetch_transactions(address: str, cfg: EtherscanConfig) -> list[dict[str, Any]]:
    params = {
        "module": "account",
        "action": "txlist",
        "address": address,
        "startblock": cfg.start_block,
        "endblock": cfg.end_block,
        "sort": "desc",
    }
    if cfg.api_key:
        params["apikey"] = cfg.api_key
    data = await async_fetch_json(_ETHERSCAN_API, params=params, timeout=15.0)
    if not isinstance(data, dict):
        raise ValueError("Unexpected response from Etherscan")
    if data.get("status") != "1":
        log.warning("etherscan_non_ok", address=address, code=data.get("status"), message=data.get("message"))
        return []
    result = data.get("result")
    if not isinstance(result, list):
        return []
    return [item for item in result if isinstance(item, dict)]


def _format_event(tx: dict[str, Any], *, origin: str, threshold_eth: float) -> dict[str, Any] | None:
    value_raw = tx.get("value")
    if not isinstance(value_raw, str):
        return None
    try:
        value_eth = int(value_raw) / _WEI_IN_ETH
    except Exception:
        return None
    if value_eth < threshold_eth:
        return None
    direction = "out" if tx.get("from", "").lower() == origin else "in"
    return {
        "hash": tx.get("hash"),
        "block_number": tx.get("blockNumber"),
        "timestamp": tx.get("timeStamp"),
        "from": tx.get("from"),
        "to": tx.get("to"),
        "value_eth": value_eth,
        "gas_price": tx.get("gasPrice"),
        "status": tx.get("txreceipt_status"),
        "direction": direction,
        "source": "etherscan",
    }


async def collect_whale_events(cfg: EtherscanConfig) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for address in cfg.addresses:
        txs = await _fetch_transactions(address, cfg)
        for tx in txs:
            event = _format_event(tx, origin=address, threshold_eth=cfg.threshold_eth)
            if event:
                events.append(event)
        if cfg.sleep_ms:
            await asyncio.sleep(cfg.sleep_ms / 1000.0)
    events.sort(key=lambda e: e.get("timestamp") or 0, reverse=True)
    total_eth = sum(event.get("value_eth") or 0.0 for event in events)
    return {
        "addresses": cfg.addresses,
        "threshold_eth": cfg.threshold_eth,
        "count": len(events),
        "total_eth": total_eth,
        "events": events,
    }


def write_export(payload: dict[str, Any], *, cfg: EtherscanConfig, filename: str | None = None) -> Path:
    cfg.export_dir.mkdir(parents=True, exist_ok=True)
    name = filename or "etherscan_whale_events.json"
    path = cfg.export_dir / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("etherscan_export_written", path=str(path), events=payload.get("count"))
    return path


async def refresh(cfg: EtherscanConfig) -> Path | None:
    if not cfg.enabled:
        log.info("etherscan_disabled")
        return None
    if not cfg.api_key:
        log.warning("etherscan_missing_api_key")
        return None
    if not cfg.addresses:
        log.warning("etherscan_no_addresses")
        return None
    payload = await collect_whale_events(cfg)
    return write_export(payload, cfg=cfg)


async def collect_balance_records(cfg: EtherscanConfig) -> dict[str, Any] | None:
    if not cfg.enabled:
        log.info("etherscan_balances_disabled")
        return None
    if not cfg.addresses:
        log.warning("etherscan_balances_no_addresses")
        return None
    balances = await _fetch_balances(cfg.addresses, cfg)
    if not balances:
        log.warning("etherscan_balances_empty")
        return None
    entries: list[dict[str, Any]] = []
    total_eth = 0.0
    for item in balances:
        account = item.get("account")
        raw_balance = item.get("balance")
        if not isinstance(account, str) or not isinstance(raw_balance, str):
            continue
        try:
            balance_eth = int(raw_balance) / _WEI_IN_ETH
        except Exception:
            continue
        entries.append({"address": account.lower(), "balance_eth": balance_eth})
        total_eth += balance_eth
    if not entries:
        log.warning("etherscan_balances_no_valid_entries")
        return None
    now_ts = int(time())
    payload = {
        "generated_at": now_ts,
        "total_eth": total_eth,
        "addresses": entries,
        "source": _SOURCE,
        "address_count": len(entries),
    }
    try:
        write_export(payload, cfg=cfg, filename="etherscan_whale_balances.json")
    except Exception:
        log.warning("etherscan_balances_write_failed", exc_info=True)
    _update_whale_metrics(entries, total_eth, now_ts)
    record: dict[str, Any] = {
        "timestamp": now_ts,
        "asset": "ETH",
        "symbol": "ETH",
        "chain": "ethereum",
        "metric_name": "insider_whale_balance_total",
        "value": total_eth,
        "source": "etherscan",
        "confidence_score": 1.0,
        "addresses": entries,
        "metadata": {
            "address_count": len(entries),
            "source": _SOURCE,
        },
    }
    return record


def _update_whale_metrics(entries: list[dict[str, Any]], total_eth: float, timestamp: int) -> None:
    """Push Prometheus gauges for aggregated whale balances."""
    try:
        WHALE_BALANCE_TOTAL.labels(source=_SOURCE).set(total_eth)
        WHALE_BALANCE_LAST_UPDATED.labels(source=_SOURCE).set(timestamp)
        current_addresses: set[str] = set()
        for entry in entries:
            addr = entry.get("address")
            bal = entry.get("balance_eth")
            if not isinstance(addr, str) or not isinstance(bal, int | float):
                continue
            addr_norm = addr.lower()
            WHALE_BALANCE_PER_ADDRESS.labels(source=_SOURCE, address=addr_norm).set(float(bal))
            current_addresses.add(addr_norm)
        stale_addresses = _PREVIOUS_WHALE_ADDRESSES.difference(current_addresses)
        for stale in stale_addresses:
            try:
                WHALE_BALANCE_PER_ADDRESS.remove(_SOURCE, stale)
            except KeyError:
                continue
            except Exception:
                log.warning("etherscan_balances_metric_remove_failed", address=stale, exc_info=True)
        _PREVIOUS_WHALE_ADDRESSES.clear()
        _PREVIOUS_WHALE_ADDRESSES.update(current_addresses)
    except Exception:  # pragma: no cover - metrics updates must never fail collection
        log.warning("etherscan_balances_metric_update_failed", exc_info=True)


def reset_whale_metric_state() -> None:
    """Testing helper to clear cached whale metrics for deterministic assertions."""
    # Copy before clearing to attempt removal even if Gauge.clear is unavailable.
    previous = list(_PREVIOUS_WHALE_ADDRESSES)
    try:
        WHALE_BALANCE_PER_ADDRESS.clear()
    except AttributeError:
        for addr in previous:
            try:
                WHALE_BALANCE_PER_ADDRESS.remove(_SOURCE, addr)
            except Exception:
                continue
    except Exception:
        # Keep silent during cleanup to avoid hiding primary test assertions.
        pass
    _PREVIOUS_WHALE_ADDRESSES.clear()


__all__ = [
    "EtherscanConfig",
    "collect_whale_events",
    "load_config",
    "refresh",
    "write_export",
    "collect_balance_records",
    "reset_whale_metric_state",
]

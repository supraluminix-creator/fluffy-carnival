"""
Collector On-chain (TxCount, Hashrate, SOPR, etc.)
Prod-safe, async, retry/backoff, cache TTL, fallback
"""

import csv
import io
import time
from typing import Any, TypedDict

import httpx
import structlog
from diskcache import Cache
from prometheus_client import Counter, Summary
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()
cache: Cache = Cache(".cache")


class TxCountRecord(TypedDict):
    timestamp: int | None
    asset: str
    metric_name: str  # "txcount"
    value: int
    source: str
    confidence_score: float


class HashrateRecord(TypedDict):
    timestamp: int | None
    asset: str
    metric_name: str  # "hashrate"
    value: float
    source: str
    confidence_score: float


class SoprRecord(TypedDict):
    timestamp: int | None
    asset: str
    metric_name: str  # "sopr"
    value: float
    source: str
    confidence_score: float

ONCHAIN_LATENCY = Summary('onchain_latency_seconds', 'Latency of On-chain API calls')
ONCHAIN_ERRORS = Counter('onchain_errors_total', 'Total On-chain API errors')
ONCHAIN_SUCCESS = Counter('onchain_success_total', 'Total On-chain API successes')

@ONCHAIN_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_txcount(
    symbol: str,
    etherscan_api_key: str | None = None,
    cache_ttl: int = 300
) -> TxCountRecord | None:
    """
    Fetch transaction count (block height) from Blockchain.info (Main) with fallback to Etherscan (Backup).

    Parameters
    ----------
    symbol : str
        Crypto symbol (e.g., 'BTC', 'ETH').
    etherscan_api_key : Optional[str]
        API key for Etherscan (required for fallback).
    cache_ttl : int
        Cache time-to-live in seconds.

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with keys: timestamp, asset, metric_name, value, source, confidence_score.

    Example
    -------
    >>> await fetch_txcount("BTC")
    """
    key = f"onchain_txcount_{symbol}"
    if key in cache:
        log.info("onchain_cache_hit", symbol=symbol)
        cached = cache.get(key)
        if isinstance(cached, dict):  # runtime guard
            return cached  # type: ignore[return-value]
    try:
        if symbol.upper() == "BTC":
            url = "https://api.blockchain.info/q/getblockcount"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10)
                resp.raise_for_status()
                try:
                    blockcount = int(resp.text)
                except (TypeError, ValueError):
                    raise ValueError("Invalid blockcount text")
                tx_result_blockchain: TxCountRecord = {
                    "timestamp": None,
                    "asset": symbol,
                    "metric_name": "txcount",
                    "value": blockcount,
                    "source": "blockchain.info",
                    "confidence_score": 1.0,
                }
                cache.set(key, tx_result_blockchain, expire=cache_ttl)
                ONCHAIN_SUCCESS.inc()
                log.info("onchain_success", symbol=symbol, source="blockchain.info")
                return tx_result_blockchain
        elif symbol.upper() == "ETH":
            if not etherscan_api_key:
                raise ValueError("Etherscan API key required for ETH txcount")
            url = f"https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey={etherscan_api_key}"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                raw_result = data.get("result") if isinstance(data, dict) else None
                if not isinstance(raw_result, str):
                    raise ValueError("Invalid etherscan result")
                blockcount = int(raw_result, 16)
                tx_result_eth: TxCountRecord = {
                    "timestamp": None,
                    "asset": symbol,
                    "metric_name": "txcount",
                    "value": blockcount,
                    "source": "etherscan",
                    "confidence_score": 1.0,
                }
                cache.set(key, tx_result_eth, expire=cache_ttl)
                ONCHAIN_SUCCESS.inc()
                log.info("onchain_success", symbol=symbol, source="etherscan")
                return tx_result_eth
        else:
            raise NotImplementedError("Only BTC and ETH supported for txcount")
    except Exception as e:
        log.error("onchain_main_error", symbol=symbol, error=str(e))
        # Fallback for BTC: none; for ETH: try Etherscan if not already tried
        if symbol.upper() == "BTC" and etherscan_api_key:
            try:
                url = f"https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey={etherscan_api_key}"
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, timeout=10)
                    resp.raise_for_status()
                    data = resp.json()
                    raw_result = data.get("result") if isinstance(data, dict) else None
                    if not isinstance(raw_result, str):
                        raise ValueError("Invalid etherscan result")
                    blockcount = int(raw_result, 16)
                    tx_result_fb: TxCountRecord = {
                        "timestamp": None,
                        "asset": symbol,
                        "metric_name": "txcount",
                        "value": blockcount,
                        "source": "etherscan",
                        "confidence_score": 0.8,
                    }
                    cache.set(key, tx_result_fb, expire=cache_ttl)
                    ONCHAIN_SUCCESS.inc()
                    log.info("onchain_fallback_success", symbol=symbol, source="etherscan")
                    return tx_result_fb
            except Exception as e2:
                ONCHAIN_ERRORS.inc()
                log.error("onchain_fallback_error", symbol=symbol, error=str(e2))
                return None
        ONCHAIN_ERRORS.inc()
        log.error("onchain_final_error", symbol=symbol, error=str(e))
        return None

@ONCHAIN_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_hashrate(
    symbol: str = "BTC",
    cache_ttl: int = 300
) -> HashrateRecord | None:
    """
    Fetch hashrate from Blockchain.info.

    Parameters
    ----------
    symbol : str
        Crypto symbol (default: 'BTC').
    cache_ttl : int
        Cache time-to-live in seconds.

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with keys: timestamp, asset, metric_name, value, source, confidence_score.
    """
    key = f"onchain_hashrate_{symbol}"
    if key in cache:
        log.info("onchain_cache_hit", symbol=symbol)
        cached = cache.get(key)
        if isinstance(cached, dict):
            return cached  # type: ignore[return-value]
    try:
        url = "https://api.blockchain.info/q/hashrate"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
            resp.raise_for_status()
            try:
                hashrate = float(resp.text)
            except (TypeError, ValueError):
                raise ValueError("Invalid hashrate text")
            hashrate_result: HashrateRecord = {
                "timestamp": None,
                "asset": symbol,
                "metric_name": "hashrate",
                "value": hashrate,
                "source": "blockchain.info",
                "confidence_score": 1.0,
            }
            cache.set(key, hashrate_result, expire=cache_ttl)
            ONCHAIN_SUCCESS.inc()
            log.info("onchain_success", symbol=symbol, source="blockchain.info")
            return hashrate_result
    except Exception as e:
        ONCHAIN_ERRORS.inc()
        log.error("onchain_error", symbol=symbol, error=str(e))
        return None

@ONCHAIN_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_sopr(
    symbol: str = "BTC",
    cache_ttl: int = 3600
) -> SoprRecord | None:
    """
    Fetch SOPR from bitcoin-data.com (CSV, prod-safe).

    Parameters
    ----------
    symbol : str
        Crypto symbol (default: 'BTC').
    cache_ttl : int
        Cache time-to-live in seconds.

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with keys: timestamp, asset, metric_name, value, source, confidence_score.
    """
    key = f"onchain_sopr_{symbol}"
    if key in cache:
        log.info("onchain_cache_hit", symbol=symbol)
        cached = cache.get(key)
        if isinstance(cached, dict):
            return cached  # type: ignore[return-value]
    try:
        url = "https://bitcoin-data.com/v1/sopr/csv"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=20)
            resp.raise_for_status()
            text = resp.text
            f = io.StringIO(text)
            reader = csv.DictReader(f)
            last_val = None
            last_ts = None
            for row in reader:
                try:
                    v = row.get("sopr") or row.get("SOPR") or row.get("value")
                    unix = row.get("unixTs") or row.get("unix")
                    if v is None:
                        continue
                    val = float(v)
                    ts = int(unix) if unix else int(time.time())
                    last_val = val
                    last_ts = ts
                except Exception:
                    continue
            if last_val is not None:
                sopr_result: SoprRecord = {
                    "timestamp": last_ts,
                    "asset": symbol,
                    "metric_name": "sopr",
                    "value": last_val,
                    "source": "bitcoin-data.com",
                    "confidence_score": 1.0,
                }
                cache.set(key, sopr_result, expire=cache_ttl)
                ONCHAIN_SUCCESS.inc()
                log.info("onchain_success", symbol=symbol, source="bitcoin-data.com")
                return sopr_result
            else:
                ONCHAIN_ERRORS.inc()
                log.warning("onchain_sopr_no_valid_line", symbol=symbol)
                return None
    except Exception as e:
        ONCHAIN_ERRORS.inc()
        log.error("onchain_sopr_error", symbol=symbol, error=str(e))
        return None

__all__ = [
    "TxCountRecord",
    "HashrateRecord",
    "SoprRecord",
    "fetch_txcount",
    "fetch_hashrate",
    "fetch_sopr",
]

"""
Collector On-chain (TxCount, Hashrate, SOPR, etc.)
Prod-safe, async, retry/backoff, cache TTL, fallback
"""

import csv
import io
import os
import time
from typing import TypedDict, cast

import httpx
import structlog
from diskcache import Cache
from prometheus_client import Counter, Summary
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.http import async_fetch_json, async_fetch_text, async_post_json
from pipeline.instrumentation import instrument_collector
from pipeline.metrics import FALLBACK_INVOCATIONS_TOTAL

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


ONCHAIN_LATENCY = Summary("onchain_latency_seconds", "Latency of On-chain API calls")
ONCHAIN_ERRORS = Counter("onchain_errors_total", "Total On-chain API errors")
ONCHAIN_SUCCESS = Counter("onchain_success_total", "Total On-chain API successes")


@instrument_collector("onchain_txcount")
@ONCHAIN_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_txcount(
    symbol: str, etherscan_api_key: str | None = None, cache_ttl: int = 300
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
    v1_tried = False  # track if we already attempted etherscan v1 to avoid duplicate retry in fallback
    try:
        if symbol.upper() == "BTC":
            url = "https://api.blockchain.info/q/getblockcount"
            # Endpoint texte: passer par la façade pour instrumentation unifiée
            async with httpx.AsyncClient() as client:
                txt = await async_fetch_text(url, timeout=15, client=client)
                blockcount = int(txt)
            # Construire et retourner le résultat (sur succès de l'un des chemins)
            tx_result_blockchain: TxCountRecord = {
                "timestamp": None,
                "asset": symbol,
                "metric_name": "txcount",
                "value": int(blockcount),
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
            use_v2 = os.getenv("ETHERSCAN_USE_V2", "0") == "1"
            if not use_v2:
                # Prefer V1 for broad compatibility and tests
                v1_tried = True
                v1_url = f"https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey={etherscan_api_key}"
                async with httpx.AsyncClient() as client:
                    # Façade HTTP unifiée (JSON) si retries activés, sinon chemin legacy
                    if os.getenv("RETRY_HTTP_ENABLED", "1") == "1":
                        data = await async_fetch_json(v1_url, timeout=10, client=client)
                    else:
                        # Uniformiser via la façade pour mapping/metrics même sans retry
                        data = await async_fetch_json(v1_url, timeout=10, client=client)
                    raw_result = data.get("result") if isinstance(data, dict) else None
                    if not isinstance(raw_result, str) or not raw_result.startswith("0x"):
                        raise ValueError("Invalid etherscan v1 result")
                    blockcount = int(raw_result, 16)
                    tx_result_eth = cast(
                        TxCountRecord,
                        {
                            "timestamp": None,
                            "asset": symbol,
                            "metric_name": "txcount",
                            "value": blockcount,
                            "source": "etherscan",
                            "confidence_score": 1.0,
                        },
                    )
                    cache.set(key, tx_result_eth, expire=cache_ttl)
                    ONCHAIN_SUCCESS.inc()
                    log.info("onchain_success", symbol=symbol, source="etherscan")
                    return tx_result_eth
            else:
                # Etherscan V2 (header X-API-KEY)
                v2_url = "https://api.etherscan.io/v2/api?module=proxy&action=eth_blockNumber&chainid=1"
                headers = {"X-API-KEY": etherscan_api_key}
                async with httpx.AsyncClient() as client:
                    if os.getenv("RETRY_HTTP_ENABLED", "1") == "1":
                        data = await async_fetch_json(v2_url, timeout=10, headers=headers, client=client)
                    else:
                        # Uniformiser via la façade pour mapping/metrics même sans retry
                        data = await async_fetch_json(v2_url, timeout=10, headers=headers, client=client)
                    raw_result = data.get("result") if isinstance(data, dict) else None
                    if not isinstance(raw_result, str) or not raw_result.startswith("0x"):
                        raise ValueError("Invalid etherscan v2 result")
                    blockcount = int(raw_result, 16)
                    tx_result_eth = cast(
                        TxCountRecord,
                        {
                            "timestamp": None,
                            "asset": symbol,
                            "metric_name": "txcount",
                            "value": blockcount,
                            "source": "etherscan-v2",
                            "confidence_score": 1.0,
                        },
                    )
                    cache.set(key, tx_result_eth, expire=cache_ttl)
                    ONCHAIN_SUCCESS.inc()
                    log.info("onchain_success", symbol=symbol, source="etherscan-v2")
                    return tx_result_eth
        else:
            raise NotImplementedError("Only BTC and ETH supported for txcount")
    except Exception as e:
        log.error("onchain_main_error", symbol=symbol, error=str(e))
        # BTC fallback (legacy): try Etherscan v1 proxy if a key is provided
        if symbol.upper() == "BTC" and etherscan_api_key:
            try:
                v1_url = f"https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey={etherscan_api_key}"
                async with httpx.AsyncClient() as client:
                    if os.getenv("RETRY_HTTP_ENABLED", "1") == "1":
                        data = await async_fetch_json(v1_url, timeout=10, client=client)
                    else:
                        # Uniformiser via la façade pour mapping/metrics même sans retry
                        data = await async_fetch_json(v1_url, timeout=10, client=client)
                    raw_result = data.get("result") if isinstance(data, dict) else None
                    if not isinstance(raw_result, str) or not raw_result.startswith("0x"):
                        raise ValueError("Invalid etherscan v1 result")
                    blockcount = int(raw_result, 16)
                    tx_btc_fb: TxCountRecord = {
                        "timestamp": None,
                        "asset": symbol,
                        "metric_name": "txcount",
                        "value": blockcount,
                        "source": "etherscan",
                        "confidence_score": 0.7,
                    }
                    cache.set(key, tx_btc_fb, expire=cache_ttl)
                    ONCHAIN_SUCCESS.inc()
                    FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_txcount", status="success").inc()
                    log.info(
                        "onchain_fallback_success",
                        symbol=symbol,
                        source="etherscan",
                        fallback=1,
                        primary_error=type(e).__name__,
                    )
                    return tx_btc_fb
            except Exception as e_btc:
                ONCHAIN_ERRORS.inc()
                FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_txcount", status="error").inc()
                log.error(
                    "onchain_fallback_error",
                    symbol=symbol,
                    error=str(e_btc),
                    fallback=1,
                    primary_error=type(e).__name__,
                    fallback_error=type(e_btc).__name__,
                )
        # Fallback only for ETH: try alternative providers when V2 fails
        if symbol.upper() == "ETH":
            # 0) Alchemy (if configured)
            alchemy_key = os.getenv("ALCHEMY_API_KEY")
            if alchemy_key:
                try:
                    rpc_url = f"https://eth-mainnet.g.alchemy.com/v2/{alchemy_key}"
                    payload = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
                    async with httpx.AsyncClient() as client:
                        data = await async_post_json(rpc_url, json=payload, timeout=10, client=client)
                        raw = data.get("result") if isinstance(data, dict) else None
                        if not isinstance(raw, str) or not raw.startswith("0x"):
                            raise ValueError("Invalid Alchemy result")
                        blockcount = int(raw, 16)
                        tx_alch: TxCountRecord = {
                            "timestamp": None,
                            "asset": symbol,
                            "metric_name": "txcount",
                            "value": blockcount,
                            "source": "alchemy",
                            "confidence_score": 0.9,
                        }
                        cache.set(key, tx_alch, expire=cache_ttl)
                        ONCHAIN_SUCCESS.inc()
                        FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_txcount", status="success").inc()
                        log.info(
                            "onchain_fallback_success",
                            symbol=symbol,
                            source="alchemy",
                            fallback=1,
                            primary_error=type(e).__name__,
                        )
                        return tx_alch
                except Exception as e_alch:
                    ONCHAIN_ERRORS.inc()
                    FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_txcount", status="error").inc()
                    log.error(
                        "onchain_fallback_error",
                        symbol=symbol,
                        error=str(e_alch),
                        fallback=1,
                        primary_error=type(e).__name__,
                        fallback_error=type(e_alch).__name__,
                    )
            # 1) Infura (if configured)
            infura_key = os.getenv("INFURA_API_KEY")
            if infura_key:
                try:
                    rpc_url = f"https://mainnet.infura.io/v3/{infura_key}"
                    payload = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
                    async with httpx.AsyncClient() as client:
                        data = await async_post_json(rpc_url, json=payload, timeout=10, client=client)
                        raw = data.get("result") if isinstance(data, dict) else None
                        if not isinstance(raw, str) or not raw.startswith("0x"):
                            raise ValueError("Invalid Infura result")
                        blockcount = int(raw, 16)
                        tx_infura: TxCountRecord = {
                            "timestamp": None,
                            "asset": symbol,
                            "metric_name": "txcount",
                            "value": blockcount,
                            "source": "infura",
                            "confidence_score": 0.9,
                        }
                        cache.set(key, tx_infura, expire=cache_ttl)
                        ONCHAIN_SUCCESS.inc()
                        FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_txcount", status="success").inc()
                        log.info(
                            "onchain_fallback_success",
                            symbol=symbol,
                            source="infura",
                            fallback=1,
                            primary_error=type(e).__name__,
                        )
                        return tx_infura
                except Exception as e_inf:
                    ONCHAIN_ERRORS.inc()
                    FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_txcount", status="error").inc()
                    log.error(
                        "onchain_fallback_error",
                        symbol=symbol,
                        error=str(e_inf),
                        fallback=1,
                        primary_error=type(e).__name__,
                        fallback_error=type(e_inf).__name__,
                    )
            # 2) Etherscan V1 (legacy) unless already tried
            if etherscan_api_key and not v1_tried:
                try:
                    v1_url = (
                        f"https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey={etherscan_api_key}"
                    )
                    async with httpx.AsyncClient() as client:
                        if os.getenv("RETRY_HTTP_ENABLED", "1") == "1":
                            data = await async_fetch_json(v1_url, timeout=10, client=client)
                        else:
                            resp = await client.get(v1_url, timeout=10)
                            resp.raise_for_status()
                            data = resp.json()
                        raw_result = data.get("result") if isinstance(data, dict) else None
                        if not isinstance(raw_result, str) or not raw_result.startswith("0x"):
                            raise ValueError("Invalid etherscan v1 result")
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
                        FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_txcount", status="success").inc()
                        log.info(
                            "onchain_fallback_success",
                            symbol=symbol,
                            source="etherscan",
                            fallback=1,
                            primary_error=type(e).__name__,
                        )
                        return tx_result_fb
                except Exception as e2:
                    ONCHAIN_ERRORS.inc()
                    FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_txcount", status="error").inc()
                    log.error(
                        "onchain_fallback_error",
                        symbol=symbol,
                        error=str(e2),
                        fallback=1,
                        primary_error=type(e).__name__,
                        fallback_error=type(e2).__name__,
                    )
            # 3) Cloudflare Ethereum (no key)
            try:
                rpc_url = "https://cloudflare-eth.com"
                payload = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
                async with httpx.AsyncClient() as client:
                    data = await async_post_json(rpc_url, json=payload, timeout=10, client=client)
                    raw = data.get("result") if isinstance(data, dict) else None
                    if not isinstance(raw, str) or not raw.startswith("0x"):
                        raise ValueError("Invalid cloudflare-eth result")
                    blockcount = int(raw, 16)
                    tx_cf: TxCountRecord = {
                        "timestamp": None,
                        "asset": symbol,
                        "metric_name": "txcount",
                        "value": blockcount,
                        "source": "cloudflare-eth",
                        "confidence_score": 0.85,
                    }
                    cache.set(key, tx_cf, expire=cache_ttl)
                    ONCHAIN_SUCCESS.inc()
                    FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_txcount", status="success").inc()
                    log.info(
                        "onchain_fallback_success",
                        symbol=symbol,
                        source="cloudflare-eth",
                        fallback=1,
                        primary_error=type(e).__name__,
                    )
                    return tx_cf
            except Exception as e3:
                ONCHAIN_ERRORS.inc()
                FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_txcount", status="error").inc()
                log.error(
                    "onchain_fallback_error",
                    symbol=symbol,
                    error=str(e3),
                    fallback=1,
                    primary_error=type(e).__name__,
                    fallback_error=type(e3).__name__,
                )
                return None
        ONCHAIN_ERRORS.inc()
        log.error("onchain_final_error", symbol=symbol, error=str(e), primary_error=type(e).__name__)
        return None


@instrument_collector("onchain_hashrate")
@ONCHAIN_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_hashrate(symbol: str = "BTC", cache_ttl: int = 300) -> HashrateRecord | None:
    """
    Fetch BTC hashrate from Blockchain.com charts API (main), fallback to blockchain.info q/hashrate.

    Main: https://api.blockchain.info/charts/hash-rate?timespan=1days&format=json
      - use the last point values[-1].y
    Fallback: https://api.blockchain.info/q/hashrate
    """
    key = f"onchain_hashrate_{symbol}"
    if key in cache:
        log.info("onchain_cache_hit", symbol=symbol)
        cached = cache.get(key)
        if isinstance(cached, dict):
            return cached  # type: ignore[return-value]
    if symbol.upper() != "BTC":
        log.warning("onchain_hashrate_unsupported_symbol", symbol=symbol)
        return None
    try:
        chart_urls = [
            "https://api.blockchain.info/charts/hash-rate?timespan=1days&format=json",
            "https://api.blockchain.info/charts/hash-rate?timespan=3days&format=json",
            "https://api.blockchain.info/charts/hash-rate?timespan=7days&format=json",
        ]
        async with httpx.AsyncClient() as client:
            last_err = None
            retry_enabled = os.getenv("RETRY_HTTP_ENABLED", "1") == "1"
            for charts_url in chart_urls:
                try:
                    if retry_enabled:
                        data = await async_fetch_json(charts_url, timeout=15, client=client)
                    else:
                        # Uniformiser via la façade pour mapping/metrics même sans retry
                        data = await async_fetch_json(charts_url, timeout=15, client=client)
                    values = (data or {}).get("values")
                    if not isinstance(values, list) or not values:
                        raise ValueError("No values in charts/hash-rate response")
                    last = values[-1] if isinstance(values[-1], dict) else None
                    y = last.get("y") if isinstance(last, dict) else None
                    if y is None:
                        raise ValueError("Missing y in last charts point")
                    hashrate = float(y)
                    res: HashrateRecord = {
                        "timestamp": None,
                        "asset": symbol,
                        "metric_name": "hashrate",
                        "value": hashrate,
                        "source": "blockchain.com-charts",
                        "confidence_score": 1.0,
                    }
                    cache.set(key, res, expire=cache_ttl)
                    ONCHAIN_SUCCESS.inc()
                    log.info("onchain_success", symbol=symbol, source="blockchain.com-charts")
                    return res
                except Exception as e1:  # essaye l'URL suivante
                    last_err = e1
                    continue
            # si toutes les URLs charts échouent, propage la dernière erreur pour activer le fallback
            raise last_err or RuntimeError("hashrate charts failed")
    except Exception as e:
        # Fallback to q/hashrate
        try:
            async with httpx.AsyncClient() as client:
                url = "https://api.blockchain.info/q/hashrate"
                txt = await async_fetch_text(url, timeout=10, client=client)
                try:
                    fallback_val = float(txt)
                except (TypeError, ValueError) as err:
                    raise ValueError("Invalid hashrate text") from err
                res_fb: HashrateRecord = {
                    "timestamp": None,
                    "asset": symbol,
                    "metric_name": "hashrate",
                    "value": fallback_val,
                    "source": "blockchain.info",
                    "confidence_score": 0.8,
                }
                cache.set(key, res_fb, expire=cache_ttl)
                ONCHAIN_SUCCESS.inc()
                FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_hashrate", status="success").inc()
                log.info(
                    "onchain_hashrate_fallback_success",
                    symbol=symbol,
                    source="blockchain.info",
                    fallback=1,
                    primary_error=type(e).__name__,
                )
                return res_fb
        except Exception as e2:
            ONCHAIN_ERRORS.inc()
            FALLBACK_INVOCATIONS_TOTAL.labels(collector="onchain_hashrate", status="error").inc()
            log.error(
                "onchain_hashrate_fallback_error",
                symbol=symbol,
                error=str(e2),
                fallback=1,
                primary_error=type(e).__name__,
                fallback_error=type(e2).__name__,
            )
            return None


@instrument_collector("onchain_sopr")
@ONCHAIN_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_sopr(symbol: str = "BTC", cache_ttl: int = 3600) -> SoprRecord | None:
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
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as he:
                sc = he.response.status_code
                if sc in (404, 429):
                    ONCHAIN_ERRORS.inc()
                    log.error("onchain_sopr_http_error", symbol=symbol, status=sc, hard_error=1)
                    raise
                raise
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
                raise RuntimeError("No valid SOPR line parsed")
    except Exception as e:
        # For hard HTTP (404/429) we return None; others already counted; keep backward compat tests.
        if isinstance(e, httpx.HTTPStatusError):
            return None
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

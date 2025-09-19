"""
Collector DefiLlama (TVL, yield, etc.)
Prod-safe, async, retry/backoff, cache TTL, historique TVL
"""
import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from diskcache import Cache
from prometheus_client import Counter, Summary
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()
cache = Cache(".cache")

DEFI_LLAMA_LATENCY = Summary('defillama_latency_seconds', 'Latency of DefiLlama API calls')
DEFI_LLAMA_ERRORS = Counter('defillama_errors_total', 'Total DefiLlama API errors')
DEFI_LLAMA_SUCCESS = Counter('defillama_success_total', 'Total DefiLlama API successes')

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def get_chain_data(chain: str) -> dict[str, Any] | None:
    """
    Get chain data from DefiLlama API with proper error handling.
    """
    try:
        url = "https://api.llama.fi/v2/chains"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=15)
            resp.raise_for_status()
            chains_data = resp.json()
            for chain_data in chains_data:
                if chain_data.get("name", "").lower() == chain.lower():
                    return chain_data
            log.error("defillama_chain_not_found", chain=chain)
            return None
    except httpx.HTTPError as e:
        log.error("defillama_http_error", chain=chain, status_code=getattr(e.response, 'status_code', 'unknown'))
        raise
    except Exception as e:
        log.error("defillama_data_error", chain=chain, error_type=type(e).__name__, error_msg=str(e))
        raise

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def get_historical_chain_data(chain: str) -> list[list | dict] | None:
    """
    Get historical TVL data for a specific chain using the historical endpoint.
    This endpoint provides daily TVL data with timestamps.
    """
    try:
        chain_data = await get_chain_data(chain)
        if not chain_data:
            log.error("defillama_no_chain_data", chain=chain)
            return None
        exact_chain_name = chain_data.get("name")
        if not exact_chain_name:
            log.error("defillama_no_chain_name", chain=chain)
            return None
        historical_url = f"https://api.llama.fi/v2/historicalChainTvl/{exact_chain_name}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(historical_url, timeout=15)
            resp.raise_for_status()
            historical_data = resp.json()
            if not historical_data or not isinstance(historical_data, list):
                log.error("defillama_invalid_historical_data", chain=chain, data_type=type(historical_data).__name__)
                return None
            return historical_data
    except httpx.HTTPError as e:
        log.error("defillama_historical_http_error", chain=chain, status_code=getattr(e.response, 'status_code', 'unknown'))
        return None
    except Exception as e:
        log.error("defillama_historical_error", chain=chain, error_type=type(e).__name__, error_msg=str(e))
        return None

def parse_historical_point(point: list | dict) -> tuple | None:
    """
    Parse a historical data point to (timestamp, tvl).
    Supports both [timestamp, tvl] and {'date': ..., 'tvl': ...} formats.
    """
    try:
        if isinstance(point, list) and len(point) >= 2:
            return int(point[0]), float(point[1])
        elif isinstance(point, dict):
            # Try to parse ISO date or timestamp
            if "date" in point and "tvl" in point:
                # Accept both ISO date and timestamp
                try:
                    ts = int(point["date"])
                except Exception:
                    # Try ISO date string
                    try:
                        ts = int(datetime.fromisoformat(point["date"]).replace(tzinfo=UTC).timestamp())
                    except Exception:
                        return None
                return ts, float(point["tvl"])
    except Exception as e:
        log.warning("defillama_parse_point_error", error=str(e), point=point)
    return None

def calculate_historical_values(historical_data: list[list | dict], current_tvl: float) -> dict[str, float]:
    """
    Calculate historical TVL values from historical data.
    Accepts both list-of-lists and list-of-dicts.
    """
    if not historical_data:
        log.warning("defillama_no_historical_data")
        return {
            "tvlPrevDay": current_tvl,
            "tvlPrevWeek": current_tvl,
            "tvlPrevMonth": current_tvl
        }
    now = int(time.time())
    targets = {
        "tvlPrevDay": now - 86400,
        "tvlPrevWeek": now - 604800,
        "tvlPrevMonth": now - 2592000
    }
    # Parse all points to (timestamp, tvl)
    parsed_points = []
    for point in historical_data:
        parsed = parse_historical_point(point)
        if parsed:
            parsed_points.append(parsed)
    # For each target, find closest
    def find_closest(target):
        closest_value = current_tvl
        min_diff = float('inf')
        for ts, val in parsed_points:
            diff = abs(ts - target)
            if diff < min_diff:
                min_diff = diff
                closest_value = val
        return closest_value
    results = {k: find_closest(ts) for k, ts in targets.items()}
    log.info("defillama_historical_calculated", **results)
    return results

@DEFI_LLAMA_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_defillama_tvl(
    chain: str,
    cache_ttl: int = 900
) -> dict[str, Any] | None:
    """
    Fetch DeFi TVL and stats from DefiLlama with historical data.
    """
    key = f"defillama_{chain}"
    if key in cache:
        log.info("defillama_cache_hit", chain=chain)
        return cache[key]
    try:
        # Get current TVL data
        chain_data = await get_chain_data(chain)
        if not chain_data or chain_data.get("tvl") is None:
            log.error("defillama_no_tvl_data", chain=chain)
            return None
        current_tvl = chain_data.get("tvl")

        # Get historical data
        historical_data = await get_historical_chain_data(chain)

        # Calculate historical values
        historical_values = calculate_historical_values(historical_data, current_tvl)

        has_valid_historical = (
            historical_data and
            any(historical_values[k] != current_tvl for k in historical_values)
        )

        result = {
            "timestamp": int(time.time()),
            "chain": chain,
            "metric_name": "defi_tvl",
            "value": {
                "tvl": current_tvl,
                "tvlPrevDay": historical_values["tvlPrevDay"],
                "tvlPrevWeek": historical_values["tvlPrevWeek"],
                "tvlPrevMonth": historical_values["tvlPrevMonth"],
            },
            "source": "defillama",
            "confidence_score": 1.0 if has_valid_historical else 0.8
        }

        cache.set(key, result, expire=cache_ttl)
        DEFI_LLAMA_SUCCESS.inc()
        log.info("defillama_success", chain=chain, has_valid_historical=has_valid_historical)
        return result

    except Exception as e:
        DEFI_LLAMA_ERRORS.inc()
        error_msg = str(e) if str(e) else f"Exception of type {type(e).__name__} with no message"
        log.error("defillama_error", chain=chain, error=error_msg, error_type=type(e).__name__)
        return None


class DefillamaCollector:
    """
    Backward-compatible wrapper exposing sync/async TVL fetchers used by legacy tests.

    Methods:
    - fetch_tvl(chain: str) -> Optional[Dict[str, Any]]: sync wrapper
    - fetch_tvl_async(chain: str) -> Optional[Dict[str, Any]]: async wrapper
    """

    def __init__(self, cache_ttl: int = 900):
        self.cache_ttl = cache_ttl

    async def fetch_tvl_async(self, chain: str) -> dict[str, Any] | None:
        return await fetch_defillama_tvl(chain, cache_ttl=self.cache_ttl)

    def fetch_tvl(self, chain: str) -> dict[str, Any] | None:
        try:
            return asyncio.run(self.fetch_tvl_async(chain))
        except Exception as e:
            # Return None on any error to satisfy tests' robustness expectations
            log.error("defillama_fetch_sync_error", chain=chain, error=str(e))
            return None

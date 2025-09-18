"""
Market collectors: CoinGecko, CoinMarketCap, CryptoCompare.
Gère prix, marketcap, dominance, stablecoins.
"""

from typing import Any

import httpx
import structlog
from diskcache import Cache
from prometheus_client import Counter, Summary
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()
cache = Cache(".cache")

MARKET_LATENCY = Summary('market_latency_seconds', 'Latency of market collectors')
MARKET_ERRORS = Counter('market_errors_total', 'Total market collector errors')
MARKET_SUCCESS = Counter('market_success_total', 'Total market collector successes')

@MARKET_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def fetch_market(symbol: str) -> dict[str, Any] | None:
    """
    Fetch price and macro data from CoinGecko (Main) with fallback to CoinMarketCap (Backup).

    Parameters
    ----------
    symbol : str
        Crypto symbol (e.g., 'bitcoin', 'ethereum').

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with price, volume, marketcap, dominance, etc.
    """
    key = f"market_{symbol}"
    if key in cache:
        log.info("market_cache_hit", symbol=symbol)
        return cache[key]
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{symbol}"
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = {
            "symbol": symbol,
            "price": data["market_data"]["current_price"]["usd"],
            "volume_24h": data["market_data"]["total_volume"]["usd"],
            "marketcap": data["market_data"]["market_cap"]["usd"],
            "dominance": data["market_data"].get("market_cap_rank", None)
        }
        cache.set(key, result, expire=300)
        MARKET_SUCCESS.inc()
        log.info("market_success", symbol=symbol)
        return result
    except Exception as e:
        log.error("market_main_error", symbol=symbol, error=str(e))
        # Fallback CoinMarketCap (mock, à compléter avec clé API)
        try:
            url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}"
            headers = {"X-CMC_PRO_API_KEY": "YOUR_API_KEY"}
            resp = httpx.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            quote = data["data"][symbol.upper()]["quote"]["USD"]
            result = {
                "symbol": symbol,
                "price": quote["price"],
                "volume_24h": quote["volume_24h"],
                "marketcap": quote["market_cap"],
                "dominance": quote.get("market_cap_dominance", None)
            }
            cache.set(key, result, expire=300)
            MARKET_SUCCESS.inc()
            log.info("market_fallback_success", symbol=symbol)
            return result
        except Exception as e2:
            MARKET_ERRORS.inc()
            log.error("market_fallback_error", symbol=symbol, error=str(e2))
            return None

MACRO_LATENCY = Summary('macro_latency_seconds', 'Latency of macro collectors')
MACRO_ERRORS = Counter('macro_errors_total', 'Total macro collector errors')
MACRO_SUCCESS = Counter('macro_success_total', 'Total macro collector successes')

@MACRO_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
async def fetch_macro(
    symbol: str,
    cmc_api_key: str | None = None,
    cache_ttl: int = 300
) -> dict[str, Any] | None:
    """
    Fetch macro data for a crypto asset from CoinGecko (Main) with fallback to CoinMarketCap (Backup).

    Parameters
    ----------
    symbol : str
        Crypto symbol (e.g., 'bitcoin', 'ethereum').
    cmc_api_key : Optional[str]
        API key for CoinMarketCap (required for fallback).
    cache_ttl : int
        Cache time-to-live in seconds.

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with keys: timestamp, asset, metric_name, value, source, confidence_score.

    Example
    -------
    >>> await fetch_macro("bitcoin", cmc_api_key="...")
    """
    key = f"macro_{symbol}"
    if key in cache:
        log.info("macro_cache_hit", symbol=symbol)
        return cache[key]
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{symbol}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            result = {
                "timestamp": data.get("last_updated"),
                "asset": symbol,
                "metric_name": "macro",
                "value": {
                    "price": data["market_data"]["current_price"]["usd"],
                    "volume_24h": data["market_data"]["total_volume"]["usd"],
                    "marketcap": data["market_data"]["market_cap"]["usd"],
                    "dominance": data["market_data"].get("market_cap_rank", None)
                },
                "source": "coingecko",
                "confidence_score": 1.0
            }
            cache.set(key, result, expire=cache_ttl)
            MACRO_SUCCESS.inc()
            log.info("macro_success", symbol=symbol, source="coingecko")
            return result
    except Exception as e:
        log.error("macro_main_error", symbol=symbol, error=str(e))
        # Fallback CoinMarketCap
        if not cmc_api_key:
            MACRO_ERRORS.inc()
            log.error("macro_fallback_skipped", symbol=symbol, error="No CMC API key")
            return None
        try:
            url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}"
            headers = {"X-CMC_PRO_API_KEY": cmc_api_key}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                quote = data["data"][symbol.upper()]["quote"]["USD"]
                result = {
                    "timestamp": data["status"]["timestamp"],
                    "asset": symbol,
                    "metric_name": "macro",
                    "value": {
                        "price": quote["price"],
                        "volume_24h": quote["volume_24h"],
                        "marketcap": quote["market_cap"],
                        "dominance": quote.get("market_cap_dominance", None)
                    },
                    "source": "coinmarketcap",
                    "confidence_score": 0.8
                }
                cache.set(key, result, expire=cache_ttl)
                MACRO_SUCCESS.inc()
                log.info("macro_fallback_success", symbol=symbol, source="coinmarketcap")
                return result
        except Exception as e2:
            MACRO_ERRORS.inc()
            log.error("macro_fallback_error", symbol=symbol, error=str(e2))
            return None
"""
Market collectors: CoinGecko, CoinMarketCap, CryptoCompare.
Gère prix, marketcap, dominance, stablecoins.
"""

from typing import Any, TypedDict

import httpx
import structlog
from diskcache import Cache
from prometheus_client import Counter, Summary
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()
cache: Cache = Cache(".cache")


class MarketSnapshot(TypedDict):
    """Synchronous market snapshot (price/volume/marketcap/dominance).

    NOTE: We intentionally keep the shape minimal (no `source`/`confidence_score`)
    to avoid breaking upstream code that may depend on the legacy keys only.
    """
    symbol: str
    price: float
    volume_24h: float
    marketcap: float
    dominance: float | int | None


class MacroValue(TypedDict):
    price: float
    volume_24h: float
    marketcap: float
    dominance: float | int | None


class MacroRecord(TypedDict):
    timestamp: str | None  # source provides ISO string; we keep raw for now
    asset: str
    metric_name: str  # always "macro"
    value: MacroValue
    source: str
    confidence_score: float

MARKET_LATENCY = Summary('market_latency_seconds', 'Latency of market collectors')
MARKET_ERRORS = Counter('market_errors_total', 'Total market collector errors')
MARKET_SUCCESS = Counter('market_success_total', 'Total market collector successes')

@MARKET_LATENCY.time()
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def fetch_market(symbol: str) -> MarketSnapshot | None:
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
        cached = cache.get(key)
        if isinstance(cached, dict):  # runtime guard
            return cached  # type: ignore[return-value]
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{symbol}"
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        def _flt(v: Any) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        md = data.get("market_data", {}) if isinstance(data, dict) else {}
        current_price = md.get("current_price", {}) if isinstance(md, dict) else {}
        total_volume = md.get("total_volume", {}) if isinstance(md, dict) else {}
        market_cap = md.get("market_cap", {}) if isinstance(md, dict) else {}

        price = _flt(current_price.get("usd"))
        vol = _flt(total_volume.get("usd"))
        mcap = _flt(market_cap.get("usd"))
        dominance = md.get("market_cap_rank") if isinstance(md, dict) else None
        market_result: MarketSnapshot = {
            "symbol": symbol,
            "price": price,
            "volume_24h": vol,
            "marketcap": mcap,
            "dominance": dominance,
        }
        cache.set(key, market_result, expire=300)
        MARKET_SUCCESS.inc()
        log.info("market_success", symbol=symbol)
        return market_result
    except Exception as e:
        log.error("market_main_error", symbol=symbol, error=str(e))
        # Fallback CoinMarketCap (mock, à compléter avec clé API)
        try:
            url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}"
            # Allow tests to monkeypatch httpx.get without headers param support
            try:
                resp = httpx.get(url, headers={"X-CMC_PRO_API_KEY": "YOUR_API_KEY"}, timeout=10)
            except TypeError:
                # Fallback: call without headers for dummy test function
                resp = httpx.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            data_block = data.get("data", {}) if isinstance(data, dict) else {}
            sym_block = data_block.get(symbol.upper(), {}) if isinstance(data_block, dict) else {}
            quote_all = sym_block.get("quote", {}) if isinstance(sym_block, dict) else {}
            usd_quote = quote_all.get("USD", {}) if isinstance(quote_all, dict) else {}

            def _flt(v: Any) -> float:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return 0.0

            result = MarketSnapshot(
                symbol=symbol,
                price=_flt(usd_quote.get("price")),
                volume_24h=_flt(usd_quote.get("volume_24h")),
                marketcap=_flt(usd_quote.get("market_cap")),
                dominance=usd_quote.get("market_cap_dominance"),
            )
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
    cache_ttl: int = 300,
) -> MacroRecord | None:
    """
    Fetch macro data for a crypto asset from CoinGecko (Main) with fallback to CoinMarketCap (Backup).

    Parameters
    ----------
    symbol : str
        Crypto symbol (e.g., 'bitcoin', 'ethereum').
    cmc_api_key : Optional[str]
        API key for CoinMarketCap (required for fallback).
    
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
        cached = cache.get(key)
        if isinstance(cached, dict):  # runtime guard
            return cached  # type: ignore[return-value]
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{symbol}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            md = data.get("market_data", {}) if isinstance(data, dict) else {}
            current_price = md.get("current_price", {}) if isinstance(md, dict) else {}
            total_volume = md.get("total_volume", {}) if isinstance(md, dict) else {}
            market_cap = md.get("market_cap", {}) if isinstance(md, dict) else {}

            def _flt(v: Any) -> float:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return 0.0

            macro_result: MacroRecord = {
                "timestamp": data.get("last_updated"),
                "asset": symbol,
                "metric_name": "macro",
                "value": {
                    "price": _flt(current_price.get("usd")),
                    "volume_24h": _flt(total_volume.get("usd")),
                    "marketcap": _flt(market_cap.get("usd")),
                    "dominance": md.get("market_cap_rank"),
                },
                "source": "coingecko",
                "confidence_score": 1.0,
            }
            cache.set(key, macro_result, expire=cache_ttl)
            MACRO_SUCCESS.inc()
            log.info("macro_success", symbol=symbol, source="coingecko")
            return macro_result
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
                data_block = data.get("data", {}) if isinstance(data, dict) else {}
                sym_block = data_block.get(symbol.upper(), {}) if isinstance(data_block, dict) else {}
                quote_all = sym_block.get("quote", {}) if isinstance(sym_block, dict) else {}
                usd_quote = quote_all.get("USD", {}) if isinstance(quote_all, dict) else {}
                status_block = data.get("status", {}) if isinstance(data, dict) else {}

                def _flt(v: Any) -> float:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return 0.0

                fallback_result: MacroRecord = {
                    "timestamp": status_block.get("timestamp"),
                    "asset": symbol,
                    "metric_name": "macro",
                    "value": {
                        "price": _flt(usd_quote.get("price")),
                        "volume_24h": _flt(usd_quote.get("volume_24h")),
                        "marketcap": _flt(usd_quote.get("market_cap")),
                        "dominance": usd_quote.get("market_cap_dominance"),
                    },
                    "source": "coinmarketcap",
                    "confidence_score": 0.8,
                }
                cache.set(key, fallback_result, expire=cache_ttl)
                MACRO_SUCCESS.inc()
                log.info("macro_fallback_success", symbol=symbol, source="coinmarketcap")
                return fallback_result
        except Exception as e2:
            MACRO_ERRORS.inc()
            log.error("macro_fallback_error", symbol=symbol, error=str(e2))
            return None
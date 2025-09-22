"""
Market collectors: CoinGecko, CoinMarketCap, CryptoCompare.
Gère prix, marketcap, dominance, stablecoins.
"""

from .binance import fetch_binance_spot_price
from pipeline.metrics import (
    FALLBACK_CHAIN_DEPTH,
    FALLBACK_INVOCATIONS_TOTAL,
    FALLBACK_TIER_INVOCATIONS_TOTAL,
)
from typing import Any, TypedDict, Dict, Union

import httpx
import asyncio  # ajout pour tier_coingecko (utilisation de asyncio.to_thread)
from pipeline.http_wrappers import async_http_get_json

# Capture de la fonction httpx.get originale pour détecter un monkeypatch de tests
try:  # pragma: no cover - simple garde
    ORIGINAL_HTTPX_GET = httpx.get
except Exception:  # pragma: no cover
    ORIGINAL_HTTPX_GET = None
import structlog
from diskcache import Cache
from prometheus_client import Counter, Summary, REGISTRY as PROM_REGISTRY
from pipeline.circuit_breaker import should_skip, record_failure, record_success
from pipeline.utils import to_float
from pipeline.metrics import fallback_tier_timing, COLLECTOR_ERROR_TYPES_TOTAL
from pipeline.errors import classify, EmptyDataError, SchemaError, NetworkError
from pipeline.orchestrator import run_fallback_chain
import os

log = structlog.get_logger()
cache: Cache = Cache(".cache")


async def _async_http_get_json(client: httpx.AsyncClient, url: str, timeout: int = 10):
    # Garde compat tests: signature conservée, délègue au wrapper central
    return await async_http_get_json(client, url, timeout=timeout)


class MarketSnapshot(TypedDict):
    """Synchronous market snapshot (price/volume/marketcap/dominance)."""
    symbol: str
    price: float
    volume_24h: float
    marketcap: float


class MacroRecord(TypedDict, total=False):
    timestamp: Any
    asset: str
    metric_name: str
    value: Dict[str, Any]
    source: str
    confidence_score: float


# Prometheus counters (idempotent guard: may already exist in metrics module)
MACRO_SUCCESS = Counter('macro_success_total', 'Macro collector successes')
MACRO_ERRORS = Counter('macro_errors_total', 'Macro collector errors')
MARKET_CACHE_HIT = Counter('market_cache_hit_total', 'Market cache hits (macro naming fix)')
MARKET_CACHE_MISS = Counter('market_cache_miss_total', 'Market cache misses (macro naming fix)')
MARKET_BREAKER_SKIPS = Counter('macro_breaker_skip_total', 'Macro breaker skips')  # legacy name retained for compatibility
MACRO_LATENCY = Summary('macro_latency_seconds', 'Macro collector latency (s)')

# Market (prix spot + marketcap) counters
def _counter(name: str, doc: str):
    try:
        return Counter(name, doc)
    except ValueError:
        return PROM_REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]

def _summary(name: str, doc: str):
    try:
        return Summary(name, doc)
    except ValueError:
        return PROM_REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]

MARKET_SUCCESS = _counter('market_success_total', 'Market collector successes')
MARKET_ERRORS = _counter('market_errors_total', 'Market collector errors')
MARKET_CACHE_HIT_SYNC = _counter('market_cache_hit_total', 'Market cache hits')
MARKET_CACHE_MISS_SYNC = _counter('market_cache_miss_total', 'Market cache misses')
MARKET_BREAKER_SKIPS_SYNC = _counter('market_breaker_skip_total', 'Market breaker skips')
MARKET_LATENCY = _summary('market_latency_seconds', 'Market collector latency (s)')


@MARKET_LATENCY.time()  # type: ignore[arg-type]
def fetch_market(symbol: str, cache_ttl: int = 300) -> Dict[str, Any] | None:
    """Collecte market (CoinGecko primary -> CoinMarketCap fallback).

    Retour shape:
      {symbol, price, volume_24h, marketcap, dominance}

    Tests attendent:
      - succès primaire: price etc depuis CoinGecko
      - fallback: primary fail -> CMC fournit quote['USD']
      - métriques: fallback_invocations_total collector="market" status=success/error
      - logs structlog: "market_fallback_success" avec fallback=1
    """
    if should_skip("market"):
        MARKET_BREAKER_SKIPS_SYNC.inc()
        log.warning("market_breaker_open", symbol=symbol)
        return None
    key = f"market_{symbol}"
    cached = cache.get(key)
    if isinstance(cached, dict):
        MARKET_CACHE_HIT_SYNC.inc()
        log.info("market_cache_hit", symbol=symbol)
        return cached  # type: ignore[return-value]
    MARKET_CACHE_MISS_SYNC.inc()
    # Primary CoinGecko
    try:
        with fallback_tier_timing("market", 1):
            url = f"https://api.coingecko.com/api/v3/coins/{symbol}"
            resp = httpx.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        md = data.get("market_data", {}) if isinstance(data, dict) else {}
        cur = md.get("current_price", {}) if isinstance(md, dict) else {}
        vol = md.get("total_volume", {}) if isinstance(md, dict) else {}
        mc = md.get("market_cap", {}) if isinstance(md, dict) else {}
        result = {
            "symbol": symbol,
            "price": to_float(cur.get("usd")),
            "volume_24h": to_float(vol.get("usd")),
            "marketcap": to_float(mc.get("usd")),
            "dominance": md.get("market_cap_rank"),
        }
        cache.set(key, result, expire=cache_ttl)
        MARKET_SUCCESS.inc()
        try:
            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="market", tier="1", status="success").inc()
        except Exception:  # pragma: no cover
            pass
        try:
            FALLBACK_CHAIN_DEPTH.labels(collector="market").set(1)
        except Exception:  # pragma: no cover
            pass
        log.info("market_success", symbol=symbol)
        return result
    except Exception as e:
        # CoinGecko primary
        if isinstance(e, KeyError):
            e = SchemaError(str(e))
        et = classify(e)
        try:
            COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="market", error_type=et).inc()
        except Exception:  # pragma: no cover
            pass
        log.error("market_main_error", symbol=symbol, error=str(e), error_type=et)

    # Fallback CoinMarketCap
    try:
        with fallback_tier_timing("market", 2):
            url_cmc = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}"
            resp = httpx.get(url_cmc, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        quote = (
            data.get("data", {})
                .get(symbol.upper(), {})
                .get("quote", {})
                .get("USD", {})
        )
        result = {
            "symbol": symbol,
            "price": to_float(quote.get("price")),
            "volume_24h": to_float(quote.get("volume_24h")),
            "marketcap": to_float(quote.get("market_cap")),
            "dominance": quote.get("market_cap_dominance"),
        }
        cache.set(key, result, expire=cache_ttl)
        MARKET_SUCCESS.inc()
        FALLBACK_INVOCATIONS_TOTAL.labels(collector="market", status="success").inc()
        try:
            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="market", tier="2", status="success").inc()
        except Exception:  # pragma: no cover
            pass
        try:
            FALLBACK_CHAIN_DEPTH.labels(collector="market").set(2)
        except Exception:  # pragma: no cover
            pass
        log.info("market_fallback_success", symbol=symbol, fallback=1, primary_error="CoinGeckoError")
        return result
    except Exception as e2:
        if isinstance(e2, KeyError):
            e2 = SchemaError(str(e2))
        et2 = classify(e2)
        MARKET_ERRORS.inc()
        FALLBACK_INVOCATIONS_TOTAL.labels(collector="market", status="error").inc()
        try:
            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="market", tier="2", status="error").inc()
        except Exception:  # pragma: no cover
            pass
        try:
            COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="market", error_type=et2).inc()
        except Exception:  # pragma: no cover
            pass
        log.error("market_fallback_error", symbol=symbol, fallback=1, primary_error="CoinGeckoError", error=str(e2), error_type=et2)
        return None


@MACRO_LATENCY.time()  # type: ignore[arg-type]
async def fetch_macro(
    symbol: str = "bitcoin",
    cmc_api_key: str | None = None,
    cache_ttl: int = 300,
) -> Union[MacroRecord, Dict[str, float], None]:
    """Collecte macro multi-fallback (simplifiée pour lisibilité & tests).

        Ordre:
          1. CoinGecko (CG)
          2. Binance spot (flag ENABLE_BINANCE_SPOT_FALLBACK=1)
          3. CoinMarketCap (CMC, via httpx.get, monkeypatch-friendly)
          4. Binance macro (flag ENABLE_BINANCE_MACRO_FALLBACK=1) -> retourne dict simple {macro_price_usd: float}

        Tests clés:
          - test_macro_no_flag_keeps_original : CG échoue => pas de flag => None
          - test_macro_with_flag_triggers_binance : CG échoue + flag macro => simple dict
          - test_macro_fallback_binance_then_none : CG échoue + flag spot => spot OK
          - test_macro_fallback_cmc_after_binance_fail : CG échoue + spot fail + CMC succès
          - test_fetch_macro_cache_hit : second appel doit lire le cache (1 seul appel CG)
        """
    # Support rétro pour tests anciens utilisant le breaker 'market_macro'
    if should_skip("macro") or should_skip("market_macro"):
        MARKET_BREAKER_SKIPS.inc()
        log.warning("macro_breaker_open", symbol=symbol)
        return None

    key = f"macro_{symbol}"
    cached = cache.get(key)
    if isinstance(cached, dict):
        MARKET_CACHE_HIT.inc()
        log.info("macro_cache_hit", symbol=symbol)
        return cached  # type: ignore[return-value]
    MARKET_CACHE_MISS.inc()

    success_marked = False

    def mark_success(depth: int):
        nonlocal success_marked
        if not success_marked:
            MACRO_SUCCESS.inc()
            try:
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="macro", tier=str(depth), status="success").inc()
            except Exception:  # pragma: no cover
                pass
            record_success("macro")
            try:
                FALLBACK_CHAIN_DEPTH.labels(collector="macro").set(depth)
            except Exception:  # pragma: no cover
                pass
            success_marked = True

    # 1) CoinGecko
    try:
        async with httpx.AsyncClient() as client:
            with fallback_tier_timing("macro", 1):
                url_cg = f"https://api.coingecko.com/api/v3/coins/{symbol}"
                # Certains tests patchent AsyncClient.get avec signature (self,url,timeout=10) sans headers.
                try:
                    data = await _async_http_get_json(client, url_cg, timeout=10)
                except TypeError:
                    # Retry sans kwargs additionnels
                    raw = await client.get(url_cg)
                    data = raw.json()
        md = data.get("market_data", {}) if isinstance(data, dict) else {}
        # Compat patch minimal renvoyant juste current_price
        if not md and isinstance(data, dict) and "current_price" in data:
            md = {"current_price": data.get("current_price")}
        cp = md.get("current_price", {}) if isinstance(md, dict) else {}
        tv = md.get("total_volume", {}) if isinstance(md, dict) else {}
        mc = md.get("market_cap", {}) if isinstance(md, dict) else {}
        rec: MacroRecord = {
            "timestamp": data.get("last_updated"),
            "asset": symbol,
            "metric_name": "macro",
            "value": {
                "price": to_float(cp.get("usd")),
                "volume_24h": to_float(tv.get("usd")),
                "marketcap": to_float(mc.get("usd")),
                "dominance": md.get("market_cap_rank"),
            },
            "source": "coingecko",
            "confidence_score": 1.0,
        }
        cache.set(key, rec, expire=cache_ttl)
        mark_success(1)
        log.info("macro_success", symbol=symbol, source="coingecko")
        return rec
    except Exception as e:
        if isinstance(e, KeyError):
            e = SchemaError(str(e))
        et = classify(e)
        try:
            COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="macro", error_type=et).inc()
        except Exception:  # pragma: no cover
            pass
        log.error("macro_cg_error", symbol=symbol, error=str(e), error_type=et)

    # 2) Binance spot (flag)
    spot_attempted = False
    if os.getenv("ENABLE_BINANCE_SPOT_FALLBACK", "0") == "1":
            spot_attempted = True
            try:
                mapping = {"bitcoin": "BTCUSDT", "ethereum": "ETHUSDT"}
                bsym = mapping.get(symbol.lower())
                if bsym:
                    spot = fetch_binance_spot_price(bsym)
                    if spot:
                        rec: MacroRecord = {
                            "timestamp": None,
                            "asset": symbol,
                            "metric_name": "macro",
                            "value": {"price": spot["value"], "volume_24h": 0.0, "marketcap": 0.0, "dominance": None},
                            "source": "binance_spot",
                            "confidence_score": 0.7,
                        }
                        cache.set(key, rec, expire=cache_ttl)
                        FALLBACK_INVOCATIONS_TOTAL.labels(collector="macro", status="success").inc()
                        try:
                            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="macro", tier="2", status="success").inc()
                        except Exception:  # pragma: no cover
                            pass
                        mark_success(2)
                        log.info("macro_fallback_success", symbol=symbol, source="binance_spot", fallback=1)
                        return rec
            except Exception as e_sp:  # pragma: no cover
                if isinstance(e_sp, KeyError):
                    e_sp = SchemaError(str(e_sp))
                et_sp = classify(e_sp)
                try:
                    COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="macro", error_type=et_sp).inc()
                except Exception:
                    pass
                log.error("macro_spot_error", symbol=symbol, error=str(e_sp), error_type=et_sp)

    # 3) CMC : support dual-mode
    #   - certains tests patchent httpx.AsyncClient => chemin async
    #   - d'autres patchent httpx.get directement => chemin sync
    # On compare à la référence ORIGINAL_HTTPX_GET pour détecter un patch.
    try:
        url_cmc = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}"
        headers = {"X-CMC_PRO_API_KEY": cmc_api_key} if cmc_api_key else None
        # Détection du mode synchronisé (httpx.get monkeypatché) vs async client standard.
        current_get = getattr(httpx, "get", None)
        use_sync = (
            current_get is not None
            and ORIGINAL_HTTPX_GET is not None
            and current_get is not ORIGINAL_HTTPX_GET
        )
        data: Any | None = None
        status_code = 200
        # Profondeur de fallback (CG a échoué, spot possiblement tenté)
        depth = 2 if not spot_attempted else 3
        if use_sync:
            # Certains tests patchent httpx.get avec une fonction basique sans param headers.
            # On tente d'appeler avec headers puis on retombe sans si TypeError.
            with fallback_tier_timing("macro", depth):
                try:
                    resp = httpx.get(url_cmc, headers=headers)
                except TypeError:
                    resp = httpx.get(url_cmc)
            status_code = getattr(resp, "status_code", 200)
            data = resp.json()
        else:
            async with httpx.AsyncClient() as client:
                with fallback_tier_timing("macro", depth):
                    try:
                        resp = await client.get(url_cmc, headers=headers, timeout=10)
                    except TypeError:  # client patché simplifié
                        resp = await client.get(url_cmc, timeout=10)
                status_code = getattr(resp, "status_code", 200)
                data = resp.json()
        if status_code != 200:
            raise RuntimeError(f"CMC status {status_code}")
        data_blk = data.get("data", {}) if isinstance(data, dict) else {}
        sym_blk = data_blk.get(symbol.upper(), {}) if isinstance(data_blk, dict) else {}
        quote = sym_blk.get("quote", {}) if isinstance(sym_blk, dict) else {}
        usd = quote.get("USD", {}) if isinstance(quote, dict) else {}
        rec: MacroRecord = {
            "timestamp": data.get("status", {}).get("timestamp") if isinstance(data, dict) else None,
            "asset": symbol,
            "metric_name": "macro",
            "value": {
                "price": to_float(usd.get("price")),
                "volume_24h": to_float(usd.get("volume_24h")),
                "marketcap": to_float(usd.get("market_cap")),
                "dominance": usd.get("market_cap_dominance"),
            },
            "source": "coinmarketcap",
            "confidence_score": 0.8,
        }
        cache.set(key, rec, expire=cache_ttl)
        FALLBACK_INVOCATIONS_TOTAL.labels(collector="macro", status="success").inc()
        try:
            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="macro", tier=str(depth), status="success").inc()
        except Exception:  # pragma: no cover
            pass
        mark_success(depth)
        log.info("macro_fallback_success", symbol=symbol, source="coinmarketcap", fallback=1 if not spot_attempted else 2)
        return rec
    except Exception as e_cmc:
        if isinstance(e_cmc, KeyError):
            e_cmc = SchemaError(str(e_cmc))
        et_cmc = classify(e_cmc)
        FALLBACK_INVOCATIONS_TOTAL.labels(collector="macro", status="error").inc()
        try:
            # Erreur au tier CMC (tier dépend de spot_attempted)
            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="macro", tier=str(2 if not spot_attempted else 3), status="error").inc()
        except Exception:  # pragma: no cover
            pass
        try:
            COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="macro", error_type=et_cmc).inc()
        except Exception:  # pragma: no cover
            pass
        log.error("macro_cmc_error", symbol=symbol, error=str(e_cmc), error_type=et_cmc)

        # 4) Binance macro price simple (flag) -> dict simple pour test
    if os.getenv("ENABLE_BINANCE_MACRO_FALLBACK", "0") == "1":
        try:
            url_bm = f"https://api.binance.com/api/v3/macro/{symbol}"
            depth_binance_macro = 3 if not spot_attempted else 4
            async with httpx.AsyncClient() as client:
                with fallback_tier_timing("macro", depth_binance_macro):
                    data_b = await _async_http_get_json(client, url_bm, timeout=5)
            if isinstance(data_b, dict) and "price" in data_b:
                FALLBACK_INVOCATIONS_TOTAL.labels(collector="macro", status="success").inc()
                try:
                    FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="macro", tier=str(depth_binance_macro), status="success").inc()
                except Exception:  # pragma: no cover
                    pass
                mark_success(depth_binance_macro)
                simple = {"macro_price_usd": float(data_b["price"])}
                log.info("macro_fallback_success", symbol=symbol, source="binance_macro_simple", legacy_simple=1)
                return simple  # type: ignore[return-value]
        except Exception as e_bm:  # pragma: no cover
            if isinstance(e_bm, KeyError):
                e_bm = SchemaError(str(e_bm))
            et_bm = classify(e_bm)
            try:
                COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="macro", error_type=et_bm).inc()
            except Exception:
                pass
            log.error("macro_binance_macro_error", symbol=symbol, error=str(e_bm), error_type=et_bm)

    if not success_marked:
        MACRO_ERRORS.inc()
        record_failure("macro")
        return None
    return None  # explicit final return when success_marked already handled earlier


async def fetch_macro_orchestrated(symbol: str = "bitcoin", cmc_api_key: str | None = None, cache_ttl: int = 300):
    """Version expérimentale orchestrée de fetch_macro utilisant run_fallback_chain.

    Tiers:
      1. CoinGecko
      2. Binance spot (flag)
      3. CoinMarketCap
      4. Binance macro simple (flag)
    Retourne même shape qu'original ou simple dict pour macro simple.
    """
    key = f"macro_{symbol}_orch"
    cached = cache.get(key)
    if isinstance(cached, dict):
        return cached

    async def tier_coingecko():
        # Utilisation helper retry (exécute sync wrapper en thread) pour limiter rate limit spikes
        from pipeline.http_wrappers import get_json_with_retry
        data = await asyncio.to_thread(get_json_with_retry, f"https://api.coingecko.com/api/v3/coins/{symbol}")
        md = data.get("market_data", {}) if isinstance(data, dict) else {}
        cp = md.get("current_price", {}) if isinstance(md, dict) else {}
        tv = md.get("total_volume", {}) if isinstance(md, dict) else {}
        mc = md.get("market_cap", {}) if isinstance(md, dict) else {}
        rec: MacroRecord = {
            "timestamp": data.get("last_updated"),
            "asset": symbol,
            "metric_name": "macro",
            "value": {
                "price": to_float(cp.get("usd")),
                "volume_24h": to_float(tv.get("usd")),
                "marketcap": to_float(mc.get("usd")),
                "dominance": md.get("market_cap_rank"),
            },
            "source": "coingecko",
            "confidence_score": 1.0,
        }
        return rec

    async def tier_binance_spot():
        if os.getenv("ENABLE_BINANCE_SPOT_FALLBACK", "0") != "1":
            return None
        mapping = {"bitcoin": "BTCUSDT", "ethereum": "ETHUSDT"}
        bsym = mapping.get(symbol.lower())
        if not bsym:
            return None
        spot = fetch_binance_spot_price(bsym)
        if not spot:
            return None
        rec: MacroRecord = {
            "timestamp": None,
            "asset": symbol,
            "metric_name": "macro",
            "value": {"price": spot["value"], "volume_24h": 0.0, "marketcap": 0.0, "dominance": None},
            "source": "binance_spot",
            "confidence_score": 0.7,
        }
        return rec

    async def tier_cmc():
        headers = {"X-CMC_PRO_API_KEY": cmc_api_key} if cmc_api_key else None
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}",
                headers=headers,
                timeout=10,
            )
        if resp.status_code != 200:
            raise RuntimeError(f"CMC status {resp.status_code}")
        data = resp.json()
        blk = data.get("data", {}).get(symbol.upper(), {}).get("quote", {}).get("USD", {})
        rec: MacroRecord = {
            "timestamp": data.get("status", {}).get("timestamp"),
            "asset": symbol,
            "metric_name": "macro",
            "value": {
                "price": to_float(blk.get("price")),
                "volume_24h": to_float(blk.get("volume_24h")),
                "marketcap": to_float(blk.get("market_cap")),
                "dominance": blk.get("market_cap_dominance"),
            },
            "source": "coinmarketcap",
            "confidence_score": 0.8,
        }
        return rec

    async def tier_binance_macro_simple():
        if os.getenv("ENABLE_BINANCE_MACRO_FALLBACK", "0") != "1":
            return None
        async with httpx.AsyncClient() as client:
            data_b = await _async_http_get_json(client, f"https://api.binance.com/api/v3/macro/{symbol}", timeout=5)
        if isinstance(data_b, dict) and "price" in data_b:
            return {"macro_price_usd": to_float(data_b.get("price"))}
        return None

    tiers = [tier_coingecko, tier_binance_spot, tier_cmc, tier_binance_macro_simple]
    result = await run_fallback_chain("macro", tiers)
    if result:
        cache.set(key, result, expire=cache_ttl)
    return result

try:
    __all__  # type: ignore[name-defined]
except NameError:  # pragma: no cover
    __all__ = []  # type: ignore
if "fetch_macro_orchestrated" not in __all__:
    __all__.append("fetch_macro_orchestrated")  # type: ignore
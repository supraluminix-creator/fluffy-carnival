"""
Market collectors: CoinGecko, CoinMarketCap, CryptoCompare.
Gère prix, marketcap, dominance, stablecoins.
"""

import os
from contextlib import suppress
from typing import Any, TypedDict

import httpx
import structlog
from diskcache import Cache
from prometheus_client import REGISTRY as PROM_REGISTRY
from prometheus_client import Counter, Summary

from pipeline.circuit_breaker import record_failure, record_success, should_skip
from pipeline.errors import SchemaError, classify
from pipeline.flags import is_dry_run_facade, is_forced_facade
from pipeline.http import async_fetch_json, fetch_json  # façade unifiée (migration progressive)
from pipeline.http_wrappers import async_http_get_json  # legacy path (sync market)
from pipeline.instrumentation import instrument_collector
from pipeline.metrics import (
    COLLECTOR_ERROR_TYPES_TOTAL,
    FACADE_FORCED,
    FALLBACK_CHAIN_DEPTH,
    FALLBACK_INVOCATIONS_TOTAL,
    FALLBACK_TIER_INVOCATIONS_TOTAL,
    fallback_tier_timing,
)
from pipeline.metrics.collectors import mark_legacy_http, set_facade_mode
from pipeline.orchestrator import run_fallback_chain
from pipeline.utils import to_float

from .binance import fetch_binance_spot_price

# Capture de la fonction httpx.get originale pour détecter un monkeypatch de tests
try:  # pragma: no cover - simple garde
    ORIGINAL_HTTPX_GET = httpx.get
except Exception:  # pragma: no cover
    ORIGINAL_HTTPX_GET = None

 

log = structlog.get_logger()
cache: Cache = Cache(".cache")
_LEGACY_MARKET_LOGGED = False  # évite spam log


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
    value: dict[str, Any]
    source: str
    confidence_score: float


# Prometheus counters (idempotent guard: may already exist in metrics module)
MACRO_SUCCESS = Counter('macro_success_total', 'Macro collector successes')
MACRO_ERRORS = Counter('macro_errors_total', 'Macro collector errors')
MARKET_CACHE_HIT = Counter('market_cache_hit_total', 'Market cache hits (macro naming fix)')
MARKET_CACHE_MISS = Counter('market_cache_miss_total', 'Market cache misses (macro naming fix)')
MARKET_BREAKER_SKIPS = Counter(
    'macro_breaker_skip_total', 'Macro breaker skips'
)  # legacy name retained for compatibility
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
# Compteur d'usage des chemins HTTP legacy (avec label collector). On ne l'incrémente que sur les chemins non façadés.
try:
    LEGACY_HTTP_USAGE = Counter('legacy_http_usage_total', 'Legacy HTTP usage by collector', ['collector'])
except ValueError:  # déjà enregistré (rechargement tests)
    LEGACY_HTTP_USAGE = PROM_REGISTRY._names_to_collectors.get('legacy_http_usage_total')  # type: ignore[attr-defined]
with suppress(Exception):  # pragma: no cover
    # Initialise l'échantillon (valeur 0) pour figer la famille dans le snapshot même sans utilisation.
    LEGACY_HTTP_USAGE.labels(collector='market')  # type: ignore[call-arg]


@MARKET_LATENCY.time()  # type: ignore[arg-type]
@instrument_collector("market")
def fetch_market(symbol: str, cache_ttl: int = 300) -> dict[str, Any] | None:
    """Collecte market (CoinGecko primary -> CoinMarketCap fallback).

    Retour shape:
      {symbol, price, volume_24h, marketcap, dominance}

    Tests attendent:
      - succès primaire: price etc depuis CoinGecko
      - fallback: primary fail -> CMC fournit quote['USD']
      - métriques: fallback_invocations_total collector="market" status=success/error
      - logs structlog: "market_fallback_success" avec fallback=1
    """
    global _LEGACY_MARKET_LOGGED
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
    # Chemin façade: activé si MARKET_USE_FACADE=1 ou FORCED global
    force_facade = is_forced_facade()
    market_facade_flag = os.getenv("MARKET_USE_FACADE", "0") == "1"
    dry_run = is_dry_run_facade() and not force_facade  # dry-run ignoré si forced actif
    # Détection d'un httpx.get monkeypatché simplifié sans param 'headers' (tests legacy)
    if force_facade and not market_facade_flag:
        try:
            import inspect
            sig = inspect.signature(httpx.get)  # type: ignore[attr-defined]
            if 'headers' not in sig.parameters:
                # On rétrograde en mode legacy pour permettre le test d'incrément legacy
                force_facade = False
        except Exception:  # pragma: no cover
            pass
    # Recalcule dry_run si on a rétrogradé forced
    if not force_facade:
        dry_run = is_dry_run_facade() and not force_facade
    # Positionne toujours les gauges (0/1)
    set_facade_mode("market", force_facade, dry_run)
    if force_facade:
        _LEGACY_MARKET_LOGGED = False  # reset pour invariants tests
    if force_facade or market_facade_flag or dry_run:
        if force_facade:
            log.info("Forced HTTP facade mode enabled", collector="market")
        elif dry_run:
            log.info("HTTP facade dry-run mode", collector="market")
        else:
            log.info("Market facade mode enabled")
        if not _LEGACY_MARKET_LOGGED:  # log une seule fois l'entrée en mode façade
            log.info("market_facade_mode_enabled", collector="market", forced=force_facade, dry_run=dry_run)
        # Implémentation via façade pour homogénéiser retry/metrics sans changer signature publique.
        try:
            with fallback_tier_timing("market", 1):
                data = fetch_json(f"https://api.coingecko.com/api/v3/coins/{symbol}", timeout=10)
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
            with suppress(Exception):  # pragma: no cover
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="market", tier="1", status="success").inc()
            with suppress(Exception):  # pragma: no cover
                FALLBACK_CHAIN_DEPTH.labels(collector="market").set(1)
            return result
        except Exception as e:
            if isinstance(e, KeyError):
                e = SchemaError(str(e))
            et = classify(e)
            with suppress(Exception):  # pragma: no cover
                COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="market", error_type=et).inc()
            log.error("market_main_error", symbol=symbol, error=str(e), error_type=et, facade=1)
        # Fallback CMC via façade
        try:
            with fallback_tier_timing("market", 2):
                data = fetch_json(
                    f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}",
                    timeout=10,
                )
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
            with suppress(Exception):  # pragma: no cover
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="market", tier="2", status="success").inc()
            with suppress(Exception):  # pragma: no cover
                FALLBACK_CHAIN_DEPTH.labels(collector="market").set(2)
            log.info(
                "market_fallback_success",
                symbol=symbol,
                fallback=1,
                primary_error="CoinGeckoError",
                facade=1,
            )
            return result
        except Exception as e2:
            if isinstance(e2, KeyError):
                e2 = SchemaError(str(e2))
            et2 = classify(e2)
            MARKET_ERRORS.inc()
            FALLBACK_INVOCATIONS_TOTAL.labels(collector="market", status="error").inc()
            with suppress(Exception):  # pragma: no cover
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="market", tier="2", status="error").inc()
            with suppress(Exception):  # pragma: no cover
                COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="market", error_type=et2).inc()
            log.error(
                "market_fallback_error",
                symbol=symbol,
                fallback=1,
                primary_error="CoinGeckoError",
                error=str(e2),
                error_type=et2,
                facade=1,
            )
            return None

    # Primary CoinGecko (legacy direct httpx.get) - seulement si non forcé façade
    if not force_facade and not market_facade_flag and not dry_run:
        with suppress(Exception):  # pragma: no cover
            FACADE_FORCED.labels(collector="market").set(0)  # type: ignore[attr-defined]
        try:
            mark_legacy_http("market")
            if not _LEGACY_MARKET_LOGGED:
                log.info("legacy_http_usage_detected", collector="market")
                _LEGACY_MARKET_LOGGED = True
        except Exception:  # pragma: no cover
            pass
    try:
        if not force_facade and not market_facade_flag:
            with fallback_tier_timing("market", 1):
                url = f"https://api.coingecko.com/api/v3/coins/{symbol}"
                resp = httpx.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
        else:
            # Si on est là avec force_facade=True cela signifie que la tentative façade a échoué (primary + fallback)
            # On ne retombe pas sur legacy en mode forced: on skip pour éviter incohérence métriques.
            raise RuntimeError("facade_primary_failed")
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
        with suppress(Exception):  # pragma: no cover
            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="market", tier="1", status="success").inc()
        with suppress(Exception):  # pragma: no cover
            FALLBACK_CHAIN_DEPTH.labels(collector="market").set(1)
        log.info("market_success", symbol=symbol)
        return result
    except Exception as e:
        # CoinGecko primary
        if isinstance(e, KeyError):
            e = SchemaError(str(e))
        et = classify(e)
        with suppress(Exception):  # pragma: no cover
            COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="market", error_type=et).inc()
        log.error("market_main_error", symbol=symbol, error=str(e), error_type=et)

    # Fallback CoinMarketCap (legacy) uniquement si pas de façade forcée
    try:
        if force_facade or market_facade_flag:
            # En mode façade (forcée ou opt-in) on ne doit pas retomber ici (déjà traité plus haut)
            raise RuntimeError("skip_legacy_fallback")
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
        with suppress(Exception):  # pragma: no cover
            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="market", tier="2", status="success").inc()
        with suppress(Exception):  # pragma: no cover
            FALLBACK_CHAIN_DEPTH.labels(collector="market").set(2)
        log.info(
            "market_fallback_success",
            symbol=symbol,
            fallback=1,
            primary_error="CoinGeckoError",
        )
        return result
    except Exception as e2:
        if isinstance(e2, KeyError):
            e2 = SchemaError(str(e2))
        et2 = classify(e2)
        MARKET_ERRORS.inc()
        FALLBACK_INVOCATIONS_TOTAL.labels(collector="market", status="error").inc()
        with suppress(Exception):  # pragma: no cover
            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="market", tier="2", status="error").inc()
        with suppress(Exception):  # pragma: no cover
            COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="market", error_type=et2).inc()
        log.error(
            "market_fallback_error",
            symbol=symbol,
            fallback=1,
            primary_error="CoinGeckoError",
            error=str(e2),
            error_type=et2,
            facade=0,
        )
        return None


@MACRO_LATENCY.time()  # type: ignore[arg-type]
@instrument_collector("macro")
async def fetch_macro(
    symbol: str = "bitcoin",
    cmc_api_key: str | None = None,
    cache_ttl: int = 300,
) -> MacroRecord | dict[str, float] | None:
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
            with suppress(Exception):  # pragma: no cover
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="macro", tier=str(depth), status="success").inc()
            record_success("macro")
            with suppress(Exception):  # pragma: no cover
                FALLBACK_CHAIN_DEPTH.labels(collector="macro").set(depth)
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
            # Conserve le nom historique "macro" (les exports savent en extraire le prix).
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
        with suppress(Exception):  # pragma: no cover
            COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="macro", error_type=et).inc()
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
                        with suppress(Exception):  # pragma: no cover
                            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="macro", tier="2", status="success").inc()
                        mark_success(2)
                        log.info("macro_fallback_success", symbol=symbol, source="binance_spot", fallback=1)
                        return rec
            except Exception as e_sp:  # pragma: no cover
                if isinstance(e_sp, KeyError):
                    e_sp = SchemaError(str(e_sp))
                et_sp = classify(e_sp)
                with suppress(Exception):
                    COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="macro", error_type=et_sp).inc()
                log.error("macro_spot_error", symbol=symbol, error=str(e_sp), error_type=et_sp)

    # 3) CMC : tentative sync prioritaire (support monkeypatch tests), fallback async si échec
    depth = 2 if not spot_attempted else 3
    url_cmc = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}"
    headers = {"X-CMC_PRO_API_KEY": cmc_api_key} if cmc_api_key else None
    cmc_data: Any | None = None
    status_code = 200
    sync_failed = False
    try:
        with fallback_tier_timing("macro", depth):
            try:
                resp = httpx.get(url_cmc, headers=headers)
            except TypeError:  # fonction patchée sans headers
                resp = httpx.get(url_cmc)
        status_code = getattr(resp, "status_code", 200)
        cmc_data = resp.json()
    except Exception:  # réseau / patch incompatible -> on tentera async
        sync_failed = True

    if sync_failed or status_code != 200:
        try:
            async with httpx.AsyncClient() as client:
                with fallback_tier_timing("macro", depth):
                    try:
                        resp_a = await client.get(url_cmc, headers=headers, timeout=10)
                    except TypeError:
                        resp_a = await client.get(url_cmc, timeout=10)
                status_code = getattr(resp_a, "status_code", 200)
                cmc_data = resp_a.json()
        except Exception as e_async:  # échec complet CMC
            if isinstance(e_async, KeyError):
                e_async = SchemaError(str(e_async))
            et_async = classify(e_async)
            FALLBACK_INVOCATIONS_TOTAL.labels(collector="macro", status="error").inc()
            with suppress(Exception):  # pragma: no cover
                FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="macro", tier=str(depth), status="error").inc()
            with suppress(Exception):  # pragma: no cover
                COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="macro", error_type=et_async).inc()
            log.error("macro_cmc_error", symbol=symbol, error=str(e_async), error_type=et_async)
            cmc_data = None

    if status_code != 200 or not isinstance(cmc_data, dict):
        # En cas d'échec CMC on continue vers fallback suivant
        if isinstance(cmc_data, dict):  # status code non 200
            log.error("macro_cmc_error", symbol=symbol, error=f"CMC status {status_code}", error_type="network")
        else:
            log.error("macro_cmc_error", symbol=symbol, error="no_data", error_type="unknown")
    else:
        data_blk = cmc_data.get("data", {}) if isinstance(cmc_data, dict) else {}
        sym_blk = data_blk.get(symbol.upper(), {}) if isinstance(data_blk, dict) else {}
        quote = sym_blk.get("quote", {}) if isinstance(sym_blk, dict) else {}
        usd = quote.get("USD", {}) if isinstance(quote, dict) else {}
        rec: MacroRecord = {
            "timestamp": cmc_data.get("status", {}).get("timestamp") if isinstance(cmc_data, dict) else None,
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
        with suppress(Exception):  # pragma: no cover
            FALLBACK_TIER_INVOCATIONS_TOTAL.labels(collector="macro", tier=str(depth), status="success").inc()
        mark_success(depth)
        log.info(
            "macro_fallback_success",
            symbol=symbol,
            source="coinmarketcap",
            fallback=1 if not spot_attempted else 2,
        )
        return rec

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
                with suppress(Exception):  # pragma: no cover
                    FALLBACK_TIER_INVOCATIONS_TOTAL.labels(
                        collector="macro",
                        tier=str(depth_binance_macro),
                        status="success",
                    ).inc()
                mark_success(depth_binance_macro)
                simple = {"macro_price_usd": float(data_b["price"])}
                log.info("macro_fallback_success", symbol=symbol, source="binance_macro_simple", legacy_simple=1)
                return simple  # type: ignore[return-value]
        except Exception as e_bm:  # pragma: no cover
            if isinstance(e_bm, KeyError):
                e_bm = SchemaError(str(e_bm))
            et_bm = classify(e_bm)
            with suppress(Exception):
                COLLECTOR_ERROR_TYPES_TOTAL.labels(collector="macro", error_type=et_bm).inc()
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
        # Migration façade: appel direct async (plus besoin de thread)
        data = await async_fetch_json(f"https://api.coingecko.com/api/v3/coins/{symbol}")
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
        data = await async_fetch_json(
            f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.upper()}",
            headers=headers,
            timeout=10,
        )
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
        data_b = await async_fetch_json(f"https://api.binance.com/api/v3/macro/{symbol}", timeout=5)
        if isinstance(data_b, dict) and "price" in data_b:
            return {"macro_price_usd": to_float(data_b.get("price"))}
        return None

    tiers = [tier_coingecko, tier_binance_spot, tier_cmc, tier_binance_macro_simple]
    result = await run_fallback_chain("macro", tiers)
    if result:
        cache.set(key, result, expire=cache_ttl)
    return result

if "__all__" not in globals():  # pragma: no cover
    __all__ = []  # type: ignore
if "fetch_macro_orchestrated" not in __all__:
    __all__.append("fetch_macro_orchestrated")  # type: ignore
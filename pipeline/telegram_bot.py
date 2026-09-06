from __future__ import annotations

import asyncio
import io
import json
import os
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

import structlog
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import (
    AIORateLimiter,
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown

from pipeline.analysis.llm_exec import run_llm_analysis
from pipeline.assets import describe_assets, get_coingecko_id, to_perp_symbol
from pipeline.circuit_breaker import _STATES as _CB_STATES
from pipeline.collectors.binance import fetch_binance_price
from pipeline.collectors.defillama import fetch_defillama_tvl
from pipeline.collectors.derivatives import (
    fetch_bybit_funding,
    fetch_bybit_long_short_ratio,
    fetch_bybit_oi,
)
from pipeline.collectors.market import fetch_macro
from pipeline.collectors.onchain import fetch_sopr, fetch_txcount
from pipeline.collectors.whale_insider import load_latest_snapshot as load_whale_insider_snapshot
from pipeline.collectors.whales import fetch_eth_whale_balances
from pipeline.http import async_fetch_json, async_fetch_text

try:  # Optional social sentiment integration
    from integrations.grok_adapter import get_social_signals as _get_social_signals
except Exception:  # pragma: no cover - adapter not installed/configured
    _get_social_signals = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover - typing only
    import prometheus_client as _prometheus_typing  # noqa: E402

    CounterType = _prometheus_typing.Counter
    GaugeType = _prometheus_typing.Gauge
else:  # pragma: no cover - fallback when mypy not evaluating types
    CounterType = Any  # type: ignore[assignment]
    GaugeType = Any  # type: ignore[assignment]

try:  # Optional Prometheus instrumentation
    import prometheus_client as _prometheus_client  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - metrics optional
    _prometheus_client = None

if _prometheus_client is not None:
    Counter = cast(CounterType, _prometheus_client.Counter)
    Gauge = cast(GaugeType, _prometheus_client.Gauge)
else:
    Counter = cast(CounterType | None, None)
    Gauge = cast(GaugeType | None, None)

logger = structlog.get_logger(__name__)

SUPPORTED_MODELS: Sequence[str] = (
    "grok",
    "deepseek",
    "claude",
    "perplexity",
    "openrouter",
    "ollama",
    "gemini",
    "chatgpt",
    "mistral",
    "qwen",
    "messari",
    "cmc",
)

_DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", "grok")
_HEALTH_URL = os.getenv("TELEGRAM_HEALTH_URL", "http://127.0.0.1:9310/health")
_METRICS_URL = os.getenv("TELEGRAM_METRICS_URL", "http://127.0.0.1:9300/metrics")
_WHALE_MIN_VALUE = float(os.getenv("WHALE_ALERT_MIN_VALUE", "500000"))

_EXTRA_WHALE_PROVIDERS: tuple[tuple[str, str, str], ...] = (
    ("unusual_whales", "UNUSUAL_WHALES_API_URL", "UNUSUAL_WHALES_API_KEY"),
    ("cointrendz", "COINTRENDZ_API_URL", "COINTRENDZ_API_KEY"),
    ("crypto_whale_monitor", "CRYPTO_WHALE_MONITOR_URL", "CRYPTO_WHALE_MONITOR_KEY"),
    ("learn2trade", "LEARN2TRADE_API_URL", "LEARN2TRADE_API_KEY"),
    ("crypto_whale_pumps", "CRYPTO_WHALE_PUMPS_URL", "CRYPTO_WHALE_PUMPS_KEY"),
    ("satoshi_calls", "SATOSHI_CALLS_API_URL", "SATOSHI_CALLS_API_KEY"),
    ("coincodecap", "COINCODECAP_API_URL", "COINCODECAP_API_KEY"),
)

_INTERACTIONS_COUNTER: CounterType | None
_ALERT_COUNTER: CounterType | None
_MODEL_USAGE_COUNTER: CounterType | None
_WHALE_DEPTH_GAUGE: GaugeType | None

if Counter is not None:
    counter_factory = cast(Any, Counter)
    _INTERACTIONS_COUNTER = cast(
        CounterType,
        counter_factory(
        "telegram_bot_interactions_total",
        "Total Telegram bot interactions",
        labelnames=("command",),
        ),
    )
    _ALERT_COUNTER = cast(
        CounterType,
        counter_factory(
        "telegram_alert_sent_total",
        "Number of Telegram alerts pushed",
        labelnames=("channel",),
        ),
    )
    _MODEL_USAGE_COUNTER = cast(
        CounterType,
        counter_factory(
        "llm_model_usage_total",
        "LLM invocations triggered via Telegram",
        labelnames=("model",),
        ),
    )
else:  # pragma: no cover - metrics disabled
    _INTERACTIONS_COUNTER = None
    _ALERT_COUNTER = None
    _MODEL_USAGE_COUNTER = None

if Gauge is not None:
    gauge_factory = cast(Any, Gauge)
    _WHALE_DEPTH_GAUGE = cast(
        GaugeType,
        gauge_factory(
        "bot_whale_fusion_depth",
        "Depth of whale alert fusion chain",
        labelnames=("symbol",),
        ),
    )
else:  # pragma: no cover - metrics disabled
    _WHALE_DEPTH_GAUGE = None


@dataclass(slots=True)
class WhaleAlert:
    timestamp: int | None
    symbol: str | None
    amount_usd: float | None
    transaction_type: str | None
    source: str
    description: str | None
    severity: str | None = None
    confidence: float | None = None


@dataclass(slots=True)
class DerivativesSnapshot:
    open_interest: float | None
    oi_source: str | None
    funding_rate: float | None
    funding_source: str | None
    long_short_ratio: dict[str, float] | None
    lsr_source: str | None


@dataclass(slots=True)
class OnChainSnapshot:
    sopr: float | None
    sopr_source: str | None
    txcount: int | None
    txcount_source: str | None


@dataclass(slots=True)
class DefiSnapshot:
    tvl: float | None
    prev_day: float | None
    prev_week: float | None
    prev_month: float | None
    source: str | None
    confidence: float | None


@dataclass(slots=True)
class SocialSnapshot:
    provider: str | None
    summary: str | None
    items: list[dict[str, Any]]
    meta: dict[str, Any] | None


@dataclass(slots=True)
class MarketSnapshot:
    ticker: str
    coingecko_id: str | None
    price: float | None
    price_source: str | None
    sopr: float | None
    sopr_source: str | None
    macro: dict[str, Any] | None
    whale_alerts: list[WhaleAlert]
    derivatives: DerivativesSnapshot
    onchain: OnChainSnapshot
    defi: DefiSnapshot | None
    social: SocialSnapshot | None
    fused_sources: list[str]
    metrics: dict[str, float]
    breaker_state: dict[str, Any] | None


_BOT_CACHE: Bot | None = None


def _bool_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _ensure_metric_inc(counter: CounterType | None, *labels: str) -> None:
    if counter is None:
        return
    try:
        counter.labels(*labels).inc()
    except Exception:  # pragma: no cover - metrics best effort
        logger.debug("telegram_metric_increment_failed", metric=counter._name)  # type: ignore[attr-defined]


def _ensure_metric_set(gauge: GaugeType | None, labels: tuple[str, ...], value: float) -> None:
    if gauge is None:
        return
    try:
        gauge.labels(*labels).set(value)
    except Exception:  # pragma: no cover - metrics best effort
        logger.debug("telegram_metric_set_failed", metric=gauge._name, value=value)  # type: ignore[attr-defined]


def choose_llm_model(model: str | None) -> str:
    candidate = (model or "").strip().lower()
    if candidate and candidate in SUPPORTED_MODELS:
        return candidate
    if candidate:
        logger.info("telegram_llm_model_unknown", requested=model)
    return _DEFAULT_LLM_MODEL


def _escape(text: str) -> str:
    return cast(str, escape_markdown(text, version=2))


async def _collect_price(ticker: str) -> tuple[float | None, str | None]:
    symbol = to_perp_symbol(ticker)
    record = await asyncio.to_thread(fetch_binance_price, symbol)
    if not record:
        return None, None
    return float(record.get("value", 0.0)), str(record.get("source", "binance"))


async def _collect_macro(coingecko_id: str | None) -> dict[str, Any] | None:
    if not coingecko_id:
        return None
    data: Any
    try:
        data = await fetch_macro(coingecko_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("telegram_macro_collect_failed", symbol=coingecko_id, error=str(exc))
        return None
    return data if isinstance(data, dict) else None


async def _collect_sopr(ticker: str) -> tuple[float | None, str | None]:
    try:
        record = await fetch_sopr(ticker.upper())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("telegram_sopr_collect_failed", symbol=ticker, error=str(exc))
        return None, None
    if not isinstance(record, dict):
        return None, None
    value = record.get("value")
    try:
        value_f = float(value) if value is not None else None
    except (TypeError, ValueError):
        value_f = None
    return value_f, str(record.get("source", "sopr"))


async def _collect_txcount(ticker: str) -> tuple[int | None, str | None]:
    etherscan_key = os.getenv("ETHERSCAN_API_KEY")
    try:
        record = await fetch_txcount(ticker.upper(), etherscan_api_key=etherscan_key)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("telegram_txcount_collect_failed", symbol=ticker, error=str(exc))
        return None, None
    if not isinstance(record, dict):
        return None, None
    raw_value = record.get("value")
    try:
        txcount = int(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        txcount = None
    source = str(record.get("source")) if record.get("source") else "txcount"
    return txcount, source


async def _collect_derivatives(ticker: str) -> DerivativesSnapshot:
    symbol = to_perp_symbol(ticker)

    async def _safe_call(coro: asyncio.Future[Any]) -> dict[str, Any] | None:
        try:
            result = await coro
            return result if isinstance(result, dict) else None
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("telegram_derivatives_collect_failed", symbol=symbol, error=str(exc))
            return None

    oi_task = asyncio.create_task(fetch_bybit_oi(symbol))
    funding_task = asyncio.create_task(fetch_bybit_funding(symbol))
    lsr_task = asyncio.create_task(fetch_bybit_long_short_ratio(symbol))

    oi_record, funding_record, lsr_record = await asyncio.gather(
        _safe_call(oi_task),
        _safe_call(funding_task),
        _safe_call(lsr_task),
    )

    oi_value: float | None = None
    oi_source: str | None = None
    if oi_record:
        try:
            oi_value = float(oi_record.get("value"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            oi_value = None
        oi_source = str(oi_record.get("source")) if oi_record.get("source") else None

    funding_value: float | None = None
    funding_source: str | None = None
    if funding_record:
        try:
            funding_value = float(funding_record.get("value"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            funding_value = None
        funding_source = str(funding_record.get("source")) if funding_record.get("source") else None

    long_short_ratio: dict[str, float] | None = None
    lsr_source: str | None = None
    if lsr_record:
        raw_value = lsr_record.get("value")
        if isinstance(raw_value, dict):
            try:
                long_short_ratio = {
                    "buy_ratio": float(raw_value.get("buy_ratio", 0.0)),
                    "sell_ratio": float(raw_value.get("sell_ratio", 0.0)),
                }
            except (TypeError, ValueError):
                long_short_ratio = None
        lsr_source = str(lsr_record.get("source")) if lsr_record.get("source") else None

    return DerivativesSnapshot(
        open_interest=oi_value,
        oi_source=oi_source,
        funding_rate=funding_value,
        funding_source=funding_source,
        long_short_ratio=long_short_ratio,
        lsr_source=lsr_source,
    )


async def _collect_defi(chain: str | None) -> DefiSnapshot | None:
    if not chain:
        return None
    try:
        payload = await fetch_defillama_tvl(chain)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("telegram_defi_collect_failed", chain=chain, error=str(exc))
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("value") if isinstance(payload.get("value"), dict) else {}
    try:
        tvl = float(value.get("tvl")) if value else None
    except (TypeError, ValueError):
        tvl = None
    def _to_float(key: str) -> float | None:
        try:
            return float(value.get(key)) if value and value.get(key) is not None else None
        except (TypeError, ValueError):
            return None

    return DefiSnapshot(
        tvl=tvl,
        prev_day=_to_float("tvlPrevDay"),
        prev_week=_to_float("tvlPrevWeek"),
        prev_month=_to_float("tvlPrevMonth"),
        source=str(payload.get("source")) if payload.get("source") else "defillama",
        confidence=float(payload.get("confidence_score", 0.0)) if payload.get("confidence_score") is not None else None,
    )


async def _collect_social(ticker: str) -> SocialSnapshot | None:
    if _get_social_signals is None:
        return None
    try:
        data = await _get_social_signals([ticker.upper()], window=os.getenv("GROK_WINDOW", "1h"), limit=30)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("telegram_social_collect_failed", symbol=ticker, error=str(exc))
        return None
    if not isinstance(data, dict):
        return None
    items = data.get("items") if isinstance(data.get("items"), list) else []
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}

    summary_parts: list[str] = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        asset = str(item.get("asset") or ticker).upper()
        sentiment = item.get("sentiment")
        try:
            sentiment_f = float(sentiment)
        except (TypeError, ValueError):
            sentiment_f = None
        trend = ", ".join(item.get("trends", [])[:3]) if isinstance(item.get("trends"), list) else None
        line = f"{asset}: sentiment {sentiment_f:+.2f}" if sentiment_f is not None else f"{asset}: sentiment n/a"
        if trend:
            line += f" ({trend})"
        summary_parts.append(line)
    summary = "\n".join(summary_parts) if summary_parts else None

    return SocialSnapshot(
        provider=str(meta.get("source") or "grok"),
        summary=summary,
        items=[item for item in items if isinstance(item, dict)],
        meta=meta,
    )


def _breaker_snapshot() -> dict[str, Any] | None:
    try:
        states = dict(_CB_STATES)
    except Exception:  # pragma: no cover - defensive
        return None
    snapshot: dict[str, Any] = {}
    for name, state in states.items():
        try:
            is_open = bool(getattr(state, "open", False))
            opened_at = getattr(state, "opened_at", None)
            if is_open:
                snapshot[name] = {
                    "open": True,
                    "opened_at": opened_at,
                }
        except Exception:  # pragma: no cover - defensive
            continue
    return snapshot or None


async def fetch_whale_alerts(symbol: str | None = None, *, limit: int = 5) -> list[WhaleAlert]:
    asset = (symbol or "").upper() or None
    api_key = os.getenv("WHALE_ALERT_API_KEY")
    params: dict[str, Any] = {
        "start": int(datetime.utcnow().timestamp()) - 3600,
        "limit": limit,
        "min_value": int(_WHALE_MIN_VALUE),
    }
    if asset:
        params["symbol"] = asset
    headers: dict[str, str] | None = None
    if api_key:
        headers = {"X-API-Key": api_key}
    url = "https://api.whale-alert.io/v1/transactions"
    try:
        data = await async_fetch_json(url, params=params, headers=headers, timeout=15)
    except Exception as exc:
        logger.info("whale_alert_primary_failed", error=str(exc))
        data = None
    alerts: list[WhaleAlert] = []
    depth = 0
    transactions = data.get("transactions") if isinstance(data, dict) else None
    if isinstance(transactions, list):
        depth = 1

        def _build_alert(entry: dict[str, Any]) -> WhaleAlert:
            raw_amount = entry.get("amount_usd")
            try:
                amount_usd = float(raw_amount) if raw_amount is not None else None
            except (TypeError, ValueError):  # pragma: no cover - defensive
                amount_usd = None
            severity: str | None = None
            if amount_usd is not None:
                if amount_usd >= (_WHALE_MIN_VALUE * 10):
                    severity = "critical"
                elif amount_usd >= (_WHALE_MIN_VALUE * 3):
                    severity = "high"
                else:
                    severity = "moderate"
            return WhaleAlert(
                timestamp=int(entry.get("timestamp", 0)) if entry.get("timestamp") else None,
                symbol=str(entry.get("symbol")).upper() if entry.get("symbol") else asset,
                amount_usd=amount_usd,
                transaction_type=str(entry.get("transaction_type")) if entry.get("transaction_type") else None,
                source="whale-alert",
                description=entry.get("hash") or entry.get("owner"),
                severity=severity,
                confidence=1.0,
            )

        alerts = [_build_alert(entry) for entry in transactions[:limit]]
    else:
        fallback = await _fallback_whale_alerts(asset)
        if fallback:
            depth = 2
            alerts.extend(fallback)
    if alerts:
        _ensure_metric_set(_WHALE_DEPTH_GAUGE, (asset or "GLOBAL",), float(depth or 0))
    return alerts


async def _fallback_whale_alerts(symbol: str | None) -> list[WhaleAlert]:
    if symbol not in {None, "ETH"}:
        return []
    try:
        record = await fetch_eth_whale_balances()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("telegram_whale_fallback_failed", error=str(exc))
        return []
    if not isinstance(record, dict):
        return []
    addresses = record.get("addresses")
    if not isinstance(addresses, list):
        return []
    alerts: list[WhaleAlert] = []
    for entry in addresses[:5]:
        balance = entry.get("balance_usd") if isinstance(entry, dict) else None
        try:
            bal_float = float(balance) if balance is not None else None
        except (TypeError, ValueError):
            bal_float = None
        alerts.append(
            WhaleAlert(
                timestamp=None,
                symbol=symbol,
                amount_usd=bal_float,
                transaction_type="balance",
                source="etherscan-whale-fallback",
                description=entry.get("address") if isinstance(entry, dict) else None,
                severity="informational",
                confidence=0.5,
            )
        )
    return alerts


async def _pull_custom_whale_feed(
    provider: str,
    url_env: str,
    key_env: str,
    symbol: str | None,
    *,
    limit: int,
) -> list[WhaleAlert]:
    url = os.getenv(url_env)
    if not url:
        return []
    headers: dict[str, str] | None = None
    api_key = os.getenv(key_env)
    if api_key:
        headers = {"Authorization": f"Bearer {api_key}"}
    params: dict[str, Any] | None = None
    if symbol:
        params = {"symbol": symbol.upper()}
    try:
        payload = await async_fetch_json(url, params=params, headers=headers, timeout=15)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("telegram_custom_whale_failed", provider=provider, error=str(exc))
        return []
    records: list[dict[str, Any]] = []
    if isinstance(payload, list):
        records = [entry for entry in payload if isinstance(entry, dict)]
    elif isinstance(payload, dict):
        for key in ("alerts", "items", "records", "data", "results"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                records = [entry for entry in candidate if isinstance(entry, dict)]
                if records:
                    break
    alerts: list[WhaleAlert] = []
    for entry in records[:limit]:
        raw_amount = entry.get("amount_usd") or entry.get("usd_value") or entry.get("notional")
        try:
            amount_usd = float(raw_amount) if raw_amount is not None else None
        except (TypeError, ValueError):
            amount_usd = None
        severity = entry.get("severity") or entry.get("level") or entry.get("impact")
        severity_str = str(severity).lower() if severity else None
        timestamp_raw = entry.get("timestamp") or entry.get("ts") or entry.get("time")
        try:
            timestamp = int(timestamp_raw) if timestamp_raw is not None else None
        except (TypeError, ValueError):
            timestamp = None
        description = (
            entry.get("description")
            or entry.get("note")
            or entry.get("summary")
            or entry.get("tx_hash")
            or entry.get("reference")
        )
        confidence_val = entry.get("confidence") or entry.get("confidence_score")
        try:
            confidence = float(confidence_val) if confidence_val is not None else None
        except (TypeError, ValueError):
            confidence = None
        alerts.append(
            WhaleAlert(
                timestamp=timestamp,
                symbol=(entry.get("asset") or entry.get("symbol") or symbol or "").upper() or None,
                amount_usd=amount_usd,
                transaction_type=str(entry.get("type") or entry.get("event") or entry.get("action") or "alert"),
                source=provider,
                description=str(description) if description else None,
                severity=severity_str,
                confidence=confidence,
            )
        )
    return alerts


async def fuse_whale_alerts(symbol: str | None, *, limit: int = 8) -> tuple[list[WhaleAlert], list[str]]:
    primary_alerts = await fetch_whale_alerts(symbol, limit=limit)
    sources: set[str] = {alert.source for alert in primary_alerts}
    extras: list[WhaleAlert] = []

    insider_snapshot = load_whale_insider_snapshot()
    if isinstance(insider_snapshot, dict):
        records = insider_snapshot.get("records")
        if isinstance(records, list):
            for entry in records[:limit]:
                if not isinstance(entry, dict):
                    continue
                amount = entry.get("value")
                if isinstance(amount, dict):
                    amount = amount.get("usd") or amount.get("amount_usd")
                try:
                    amount_usd = float(amount) if amount is not None else None
                except (TypeError, ValueError):
                    amount_usd = None
                extras.append(
                    WhaleAlert(
                        timestamp=entry.get("timestamp") if isinstance(entry.get("timestamp"), int) else None,
                        symbol=str(entry.get("asset") or entry.get("symbol") or symbol or "").upper() or None,
                        amount_usd=amount_usd,
                        transaction_type=str(entry.get("metric_name") or entry.get("type") or "insider"),
                        source="whale-insider",
                        description=str(entry.get("trader") or entry.get("metadata") or "") or None,
                        severity="intel",
                        confidence=float(entry.get("confidence_score")) if entry.get("confidence_score") else None,
                    )
                )
            if extras:
                sources.add("whale-insider")

    for provider, url_env, key_env in _EXTRA_WHALE_PROVIDERS:
        provider_alerts = await _pull_custom_whale_feed(provider, url_env, key_env, symbol, limit=limit)
        if provider_alerts:
            extras.extend(provider_alerts)
            sources.add(provider)

    combined = primary_alerts + extras
    # Remove duplicate entries by (source, description, amount)
    seen: set[tuple[str, str | None, float | None]] = set()
    deduped: list[WhaleAlert] = []
    for alert in combined:
        key = (alert.source, alert.description, alert.amount_usd)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(alert)
    deduped.sort(key=lambda item: item.amount_usd or 0.0, reverse=True)
    limited = deduped[:limit]
    if limited:
        _ensure_metric_set(_WHALE_DEPTH_GAUGE, ((symbol or "GLOBAL").upper(),), float(len(sources)))
    return limited, sorted(sources)


async def collect_market_snapshot(ticker: str) -> MarketSnapshot:
    info = describe_assets([ticker])
    asset_info = info[0] if info else None
    coingecko = asset_info.coingecko_id if asset_info else get_coingecko_id(ticker)
    price_task = asyncio.create_task(_collect_price(ticker))
    sopr_task = asyncio.create_task(_collect_sopr(ticker))
    macro_task = asyncio.create_task(_collect_macro(coingecko))
    whales_task = asyncio.create_task(fuse_whale_alerts(ticker, limit=8))
    txcount_task = asyncio.create_task(_collect_txcount(ticker))
    derivatives_task = asyncio.create_task(_collect_derivatives(ticker))
    defi_task = asyncio.create_task(_collect_defi(asset_info.defillama_chain if asset_info else None))
    social_task = asyncio.create_task(_collect_social(ticker))
    metrics_task = asyncio.create_task(
        get_metrics_snippet(
            {
                'fallback_chain_depth{collector="macro"}',
                'fallback_chain_depth{collector="deriv_oi"}',
                'fallback_chain_depth{collector="defillama"}',
                'fallback_chain_depth{collector="onchain_txcount"}',
            }
        )
    )

    price_value, price_source = await price_task
    sopr_value, sopr_source = await sopr_task
    macro = await macro_task
    (whales, whale_sources) = await whales_task
    txcount_value, txcount_source = await txcount_task
    derivatives = await derivatives_task
    defi_snapshot = await defi_task
    social_snapshot = await social_task
    metrics = await metrics_task

    onchain_snapshot = OnChainSnapshot(
        sopr=sopr_value,
        sopr_source=sopr_source,
        txcount=txcount_value,
        txcount_source=txcount_source,
    )

    return MarketSnapshot(
        ticker=ticker.upper(),
        coingecko_id=coingecko,
        price=price_value,
        price_source=price_source,
        sopr=sopr_value,
        sopr_source=sopr_source,
        macro=macro if isinstance(macro, dict) else None,
        whale_alerts=whales,
        derivatives=derivatives,
        onchain=onchain_snapshot,
        defi=defi_snapshot,
        social=social_snapshot,
        fused_sources=whale_sources,
        metrics=metrics,
        breaker_state=_breaker_snapshot(),
    )


def format_analysis_message(snapshot: MarketSnapshot, llm_message: str, *, health: dict[str, Any] | None) -> str:
    lines: list[str] = []
    lines.append(f"*Analyse {_escape(snapshot.ticker)}*")

    if snapshot.price is not None:
        price_line = f"Prix spot: {snapshot.price:.2f} USD"
        if snapshot.price_source:
            price_line += f" (_source {_escape(snapshot.price_source)}_)"
        lines.append(price_line)

    macro = snapshot.macro or {}
    macro_value = macro.get("value") if isinstance(macro.get("value"), dict) else {}
    change = macro_value.get("price_change_pct_24h")
    if change is not None:
        try:
            change_f = float(change)
            lines.append(f"Variation 24h: {change_f:+.2f}%")
        except (TypeError, ValueError):  # pragma: no cover
            pass
    dominance = macro_value.get("dominance")
    if dominance is not None:
        with suppress(TypeError, ValueError):
            lines.append(f"Dominance: {float(dominance):.2f}")

    if snapshot.derivatives:
        deriv_parts: list[str] = []
        if snapshot.derivatives.open_interest is not None:
            oi = f"OI {snapshot.derivatives.open_interest:,.0f}"
            if snapshot.derivatives.oi_source:
                oi += f" ({_escape(snapshot.derivatives.oi_source)})"
            deriv_parts.append(oi)
        if snapshot.derivatives.funding_rate is not None:
            fr = f"Funding {snapshot.derivatives.funding_rate:.4f}"
            if snapshot.derivatives.funding_source:
                fr += f" ({_escape(snapshot.derivatives.funding_source)})"
            deriv_parts.append(fr)
        lsr = snapshot.derivatives.long_short_ratio or {}
        if lsr:
            with suppress(TypeError, ValueError):
                deriv_parts.append(
                    f"LSR B:{lsr.get('buy_ratio', 0):.1f}% / S:{lsr.get('sell_ratio', 0):.1f}%"
                    + (f" ({_escape(snapshot.derivatives.lsr_source)})" if snapshot.derivatives.lsr_source else "")
                )
        if deriv_parts:
            lines.append("Dérivés: " + "; ".join(deriv_parts))

    if snapshot.onchain:
        if snapshot.onchain.sopr is not None:
            sopr_line = f"SOPR {snapshot.onchain.sopr:.3f}"
            if snapshot.onchain.sopr_source:
                sopr_line += f" ({_escape(snapshot.onchain.sopr_source)})"
            lines.append(sopr_line)
        if snapshot.onchain.txcount is not None:
            tx_line = f"TxCount {snapshot.onchain.txcount:,}"
            if snapshot.onchain.txcount_source:
                tx_line += f" ({_escape(snapshot.onchain.txcount_source)})"
            lines.append(tx_line)

    if snapshot.defi:
        defi_parts: list[str] = []
        if snapshot.defi.tvl is not None:
            defi_parts.append(f"TVL {snapshot.defi.tvl:,.0f} USD")
        if snapshot.defi.prev_day is not None and snapshot.defi.tvl is not None:
            with suppress(ZeroDivisionError, TypeError):
                delta_day = ((snapshot.defi.tvl - snapshot.defi.prev_day) / snapshot.defi.prev_day) * 100
                defi_parts.append(f"Δ24h {delta_day:+.2f}%")
        if snapshot.defi.source:
            defi_parts.append(f"src {_escape(snapshot.defi.source)}")
        lines.append("DeFi: " + "; ".join(defi_parts))

    if snapshot.whale_alerts:
        lines.append("Whales (sources: " + ", ".join(snapshot.fused_sources) + "):")
        for alert in snapshot.whale_alerts[:4]:
            parts: list[str] = []
            if alert.amount_usd:
                parts.append(f"{alert.amount_usd:,.0f} USD")
            if alert.transaction_type:
                parts.append(alert.transaction_type)
            if alert.severity:
                parts.append(alert.severity)
            if alert.description:
                parts.append(alert.description[:48])
            lines.append(f"• {' | '.join(parts)} ({_escape(alert.source)})")

    if snapshot.social and snapshot.social.summary:
        lines.append("Social sentiment:")
        lines.extend([f"• {_escape(chunk)}" for chunk in snapshot.social.summary.splitlines()])

    if snapshot.metrics:
        fallback_lines = []
        for key, value in snapshot.metrics.items():
            fallback_lines.append(f"{key.split('{')[0]}={value:.2f}")
        if fallback_lines:
            lines.append("Metrics: " + "; ".join(fallback_lines))

    if snapshot.breaker_state:
        breakers = ", ".join(sorted(snapshot.breaker_state.keys()))
        lines.append(f"Breakers actifs: {breakers}")

    lines.append("\n*Insight LLM*:")
    lines.append(_escape(llm_message.strip()))

    if health:
        ready = health.get("ready")
        uptime = health.get("uptime_seconds") or health.get("uptime")
        lines.append("")
        lines.append(f"Health: ready={ready} uptime={uptime}")

    return "\n".join(lines)


async def get_health_snapshot() -> dict[str, Any] | None:
    try:
        data = await async_fetch_json(_HEALTH_URL, timeout=5)
        if isinstance(data, dict):
            return data
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("telegram_health_fetch_failed", error=str(exc))
    return None


async def get_metrics_snippet(metric_names: Iterable[str]) -> dict[str, float]:
    names = set(metric_names)
    if not names:
        return {}
    try:
        text = await async_fetch_text(_METRICS_URL, timeout=5)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("telegram_metrics_fetch_failed", error=str(exc))
        return {}
    snapshot: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        for metric in names:
            if line.startswith(metric):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        snapshot[metric] = float(parts[-1])
                    except ValueError:
                        continue
    return snapshot


async def _run_llm(summary_prompt: str, model: str) -> str:
    if _MODEL_USAGE_COUNTER is not None:
        _ensure_metric_inc(_MODEL_USAGE_COUNTER, model)
    result = await asyncio.to_thread(run_llm_analysis, summary_prompt, model=model)
    return cast(str, result)


def _bot_token() -> str | None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        logger.debug("telegram_token_missing")
    return token


def _bot_instance() -> Bot | None:
    global _BOT_CACHE
    token = _bot_token()
    if not token:
        return None
    if _BOT_CACHE is None:
        _BOT_CACHE = Bot(token=token)
    return _BOT_CACHE


async def send_telegram_message(text: str, *, chat_id: str | None = None) -> None:
    bot = _bot_instance()
    if bot is None:
        logger.warning("telegram_send_skipped_no_token")
        return
    target_chat = chat_id or os.getenv("TELEGRAM_CHANNEL_ID")
    if not target_chat:
        logger.warning("telegram_send_skipped_no_chat")
        return
    try:
        await bot.send_message(
            chat_id=target_chat,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
        if _ALERT_COUNTER is not None:
            _ensure_metric_inc(_ALERT_COUNTER, str(target_chat))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("telegram_send_failed", error=str(exc))


def _collect_command_args(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[str, str | None]:
    args = list(context.args or [])
    text = update.effective_message.text if update.effective_message else ""
    if not args and text:
        parts = text.split()
        if len(parts) >= 2:
            args = parts[1:]
    ticker = args[0] if args else "BTC"
    model = args[1] if len(args) >= 2 else None
    return ticker.upper(), model


async def _handle_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE, *, implicit: bool = False) -> None:
    command = "message" if implicit else "analyse"
    if _INTERACTIONS_COUNTER is not None:
        _ensure_metric_inc(_INTERACTIONS_COUNTER, command)
    ticker, model_hint = _collect_command_args(update, context)
    model = choose_llm_model(model_hint)
    try:
        snapshot = await collect_market_snapshot(ticker)
        prompt = _build_llm_prompt(snapshot, snapshot.metrics)
        llm_text = await _run_llm(prompt, model)
        health = await get_health_snapshot()
        message = format_analysis_message(snapshot, llm_text, health=health)
        await update.effective_message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)
        csv_bytes = _snapshot_to_csv(snapshot)
        if csv_bytes:
            await update.effective_message.reply_document(document=csv_bytes, filename=f"{ticker.lower()}_snapshot.csv")
    except Exception as exc:
        logger.error("telegram_analysis_failed", ticker=ticker, error=str(exc))
        health = await get_health_snapshot()
        fallback = f"Service temporairement indisponible. Health: {json.dumps(health) if health else 'n/a'}"
        await update.effective_message.reply_text(_escape(fallback), parse_mode=ParseMode.MARKDOWN_V2)


def _snapshot_to_csv(snapshot: MarketSnapshot) -> io.BytesIO | None:
    try:
        rows = [
            ("ticker", snapshot.ticker),
            ("price", snapshot.price),
            ("price_source", snapshot.price_source),
            ("sopr", snapshot.onchain.sopr if snapshot.onchain else snapshot.sopr),
            ("sopr_source", snapshot.onchain.sopr_source if snapshot.onchain else snapshot.sopr_source),
            ("txcount", snapshot.onchain.txcount if snapshot.onchain else None),
            ("txcount_source", snapshot.onchain.txcount_source if snapshot.onchain else None),
            ("oi", snapshot.derivatives.open_interest if snapshot.derivatives else None),
            ("funding_rate", snapshot.derivatives.funding_rate if snapshot.derivatives else None),
            (
                "lsr_buy",
                (snapshot.derivatives.long_short_ratio or {}).get("buy_ratio") if snapshot.derivatives else None,
            ),
            (
                "lsr_sell",
                (snapshot.derivatives.long_short_ratio or {}).get("sell_ratio") if snapshot.derivatives else None,
            ),
        ]
        buf = io.StringIO()
        buf.write("field,value\n")
        for name, value in rows:
            buf.write(f"{name},{value}\n")
        for idx, alert in enumerate(snapshot.whale_alerts[:3], start=1):
            buf.write(f"whale_{idx}_amount,{alert.amount_usd}\n")
            buf.write(f"whale_{idx}_source,{alert.source}\n")
        data = io.BytesIO(buf.getvalue().encode("utf-8"))
        data.seek(0)
        return data
    except Exception:  # pragma: no cover - defensive
        return None


def _snapshot_to_parquet(snapshot: MarketSnapshot) -> io.BytesIO | None:
    try:
        import pandas as pd  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - optional dependency
        return None
    try:
        records: list[dict[str, Any]] = []
        records.append(
            {
                "ticker": snapshot.ticker,
                "price": snapshot.price,
                "price_source": snapshot.price_source,
                "sopr": snapshot.onchain.sopr if snapshot.onchain else snapshot.sopr,
                "sopr_source": snapshot.onchain.sopr_source if snapshot.onchain else snapshot.sopr_source,
                "txcount": snapshot.onchain.txcount if snapshot.onchain else None,
                "txcount_source": snapshot.onchain.txcount_source if snapshot.onchain else None,
                "oi": snapshot.derivatives.open_interest if snapshot.derivatives else None,
                "funding_rate": snapshot.derivatives.funding_rate if snapshot.derivatives else None,
                "lsr_buy": (snapshot.derivatives.long_short_ratio or {}).get("buy_ratio")
                if snapshot.derivatives
                else None,
                "lsr_sell": (snapshot.derivatives.long_short_ratio or {}).get("sell_ratio")
                if snapshot.derivatives
                else None,
                "defi_tvl": snapshot.defi.tvl if snapshot.defi else None,
                "defi_confidence": snapshot.defi.confidence if snapshot.defi else None,
            }
        )
        df = pd.DataFrame.from_records(records)
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        buf.seek(0)
        return buf
    except Exception:  # pragma: no cover - defensive
        return None


def _build_llm_prompt(snapshot: MarketSnapshot, metrics: dict[str, float]) -> str:
    macro = snapshot.macro or {}
    macro_value = macro.get("value") if isinstance(macro.get("value"), dict) else macro
    prompt = {
        "ticker": snapshot.ticker,
        "price": snapshot.price,
        "price_source": snapshot.price_source,
        "coingecko_id": snapshot.coingecko_id,
        "macro": macro_value,
        "derivatives": asdict(snapshot.derivatives) if snapshot.derivatives else None,
        "onchain": asdict(snapshot.onchain) if snapshot.onchain else None,
        "defi": asdict(snapshot.defi) if snapshot.defi else None,
        "whales": [asdict(alert) for alert in snapshot.whale_alerts],
        "whale_sources": snapshot.fused_sources,
        "social": asdict(snapshot.social) if snapshot.social else None,
        "metrics": metrics,
        "breaker_state": snapshot.breaker_state,
    }
    return json.dumps(prompt, ensure_ascii=False)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _INTERACTIONS_COUNTER is not None:
        _ensure_metric_inc(_INTERACTIONS_COUNTER, "start")
    health = await get_health_snapshot()
    message = "Bienvenue sur le bot Prod-Safe. Utilisez /analyse BTC grok pour lancer une analyse."
    if health:
        message += f"\nHealth ready={health.get('ready')} uptime={health.get('uptime_seconds')}"
    await update.effective_message.reply_text(_escape(message), parse_mode=ParseMode.MARKDOWN_V2)


async def handle_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _INTERACTIONS_COUNTER is not None:
        _ensure_metric_inc(_INTERACTIONS_COUNTER, "alerts")
    ticker = context.args[0] if context.args else "BTC"
    alerts = await fetch_whale_alerts(ticker)
    if not alerts:
        await update.effective_message.reply_text("Aucune alerte whale récente.")
        return
    lines = [f"Alerts {ticker.upper()}:"]
    for alert in alerts[:5]:
        parts = []
        if alert.amount_usd:
            parts.append(f"{alert.amount_usd:,.0f} USD")
        if alert.transaction_type:
            parts.append(alert.transaction_type)
        if alert.description:
            parts.append(alert.description[:40])
        lines.append(" - " + " | ".join(parts) + f" ({alert.source})")
    await update.effective_message.reply_text(_escape("\n".join(lines)), parse_mode=ParseMode.MARKDOWN_V2)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_analysis(update, context, implicit=True)


def build_application() -> Application:
    token = _bot_token()
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is required to start the bot")
    application = (
        Application.builder()
        .token(token)
        .rate_limiter(AIORateLimiter(max_retries=3))
        .build()
    )
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("alerts", handle_alerts))
    application.add_handler(CommandHandler("analyse", _handle_analysis))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application


def run_polling() -> None:
    app = build_application()
    logger.info("telegram_bot_starting_polling")
    app.run_polling(close_loop=False)


async def run_telegram_alert_job() -> None:
    if not _bool_flag("ENABLE_TELEGRAM_ALERTS", False):
        logger.debug("telegram_alerts_disabled")
        return
    symbols = [s.strip().upper() for s in os.getenv("TELEGRAM_ALERT_SYMBOLS", "BTC,ETH").split(",") if s.strip()]
    threshold = float(os.getenv("TELEGRAM_SURGE_THRESHOLD", "10"))
    for symbol in symbols:
        snapshot = await collect_market_snapshot(symbol)
        macro_value = snapshot.macro.get("value") if snapshot.macro else {}
        change = macro_value.get("price_change_pct_24h") if isinstance(macro_value, dict) else None
        try:
            change_f = float(change) if change is not None else 0.0
        except (TypeError, ValueError):
            change_f = 0.0
        if abs(change_f) < threshold and not snapshot.whale_alerts:
            continue
        prompt = _build_llm_prompt(snapshot, {})
        llm_text = await _run_llm(prompt, choose_llm_model(None))
        health = await get_health_snapshot()
        message = format_analysis_message(snapshot, llm_text, health=health)
        await send_telegram_message(message)


__all__ = [
    "build_application",
    "run_polling",
    "run_telegram_alert_job",
    "send_telegram_message",
    "collect_market_snapshot",
    "format_analysis_message",
    "choose_llm_model",
    "fetch_whale_alerts",
]

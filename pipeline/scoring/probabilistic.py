from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pandas as pd
import structlog

from pipeline.assets import get_coingecko_id
from pipeline.http import async_fetch_json

log = structlog.get_logger()

_COINGECKO_MARKET_CHART = "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
_COINALYZE_BASE = "https://api.coinalyze.net/v1/market_snapshot"
_COINDESK_ORDERBOOK = "https://developers.coindesk.com/v1/cc/orderbook"


@dataclass(slots=True)
class ScoreComponents:
    volatility_annualized: float | None
    volume_funding_ratio: float | None
    funding_rate: float | None
    orderbook_imbalance: float | None
    whale_pressure: float | None
    rumour_intensity_index: float | None = None


@dataclass(slots=True)
class ScoreReport:
    symbol: str
    coingecko_id: str | None
    components: ScoreComponents
    score: float
    strategy: str
    context: dict[str, Any]


def _safe_series(values: Iterable[float]) -> pd.Series:
    return pd.Series(list(values), dtype="float64")


def _compute_volatility(prices: Iterable[float]) -> float | None:
    series = _safe_series(prices).dropna()
    if series.size < 2:
        return None
    returns = (series / series.shift(1)).dropna()
    if returns.empty:
        return None
    log_returns = returns.apply(math.log)
    if log_returns.empty:
        return None
    vol_daily = float(log_returns.std(ddof=0))
    if math.isnan(vol_daily):
        return None
    return vol_daily * math.sqrt(365)


def _normalize_volatility(vol: float | None) -> float:
    if vol is None:
        return 0.5
    # 0.0 -> 1.0 score, 200%+ -> 0.0 score
    scaled = max(0.0, min(1.0, 1.0 - vol / 2.0))
    return scaled


def _normalize_volume_ratio(ratio: float | None) -> float:
    if ratio is None:
        return 0.5
    bounded = max(0.0, min(2.0, ratio))
    return bounded / 2.0


def _normalize_funding_rate(rate: float | None) -> float:
    if rate is None:
        return 0.5
    # Neutral around zero, penalise extreme values
    return max(0.0, min(1.0, 1.0 - abs(rate) * 50))


def _normalize_orderbook_imbalance(imbalance: float | None) -> float:
    if imbalance is None:
        return 0.5
    bounded = max(-1.0, min(1.0, imbalance))
    return (bounded + 1.0) / 2.0


def _normalize_whale_pressure(pressure: float | None) -> float:
    if pressure is None:
        return 0.5
    bounded = max(-1.0, min(1.0, pressure))
    return (bounded + 1.0) / 2.0


def _normalize_rumour_intensity(intensity: float | None) -> float:
    if intensity is None:
        return 0.5
    bounded = max(-1.0, min(1.0, intensity))
    return (bounded + 1.0) / 2.0


def _compute_rumour_intensity(
    records: Iterable[dict[str, Any]] | None,
    symbol: str,
) -> tuple[float | None, str | None, float | None]:
    if not records:
        return None, None, None
    relevant: list[tuple[float, float, str]] = []
    sym_norm = symbol.upper()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        try:
            intensity = float(rec.get("value") or 0.0)
            confidence = float(rec.get("confidence") or rec.get("confidence_score") or 0.0)
        except Exception:
            continue
        rec_symbol = str(rec.get("symbol") or "").upper()
        topic = str(rec.get("topic") or "")
        if rec_symbol and rec_symbol != sym_norm and sym_norm not in topic.upper().split():
            continue
        sentiment = str(rec.get("sentiment") or "neutral")
        relevant.append((intensity, confidence, sentiment))
    if not relevant:
        return None, None, None
    mention_volume = len(relevant)
    total_intensity = sum(item[0] for item in relevant)
    total_confidence = sum(item[1] for item in relevant)
    avg_conf = total_confidence / mention_volume if mention_volume else 0.0
    avg_intensity = total_intensity / mention_volume if mention_volume else 0.0
    sentiment = relevant[-1][2]
    signal: str | None = None
    if avg_conf >= 0.7:
        if avg_intensity >= 0.6:
            signal = "buy_rumour"
        elif avg_intensity <= -0.6:
            signal = "sell_news"
    return avg_intensity, signal, avg_conf


async def fetch_coingecko_market_chart(
    *,
    coingecko_id: str,
    vs_currency: str = "usd",
    days: int = 30,
) -> pd.DataFrame:
    params = {"vs_currency": vs_currency, "days": days}
    url = _COINGECKO_MARKET_CHART.format(coin_id=coingecko_id)
    data = await async_fetch_json(url, params=params, timeout=15.0)
    prices = data.get("prices") if isinstance(data, dict) else None
    if not isinstance(prices, list):
        raise ValueError("Unexpected response from CoinGecko market chart")
    df = pd.DataFrame(prices, columns=["timestamp", "price"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True, errors="coerce")
    df = df.dropna()
    df = df.sort_values("timestamp")
    return df


async def fetch_coinalyze_snapshot(
    *,
    market: str,
    api_key: str,
) -> dict[str, Any]:
    headers = {"X-API-KEY": api_key}
    params = {"market": market}
    data = await async_fetch_json(_COINALYZE_BASE, params=params, headers=headers, timeout=10.0)
    if isinstance(data, dict):
        return data
    raise ValueError("Unexpected response from Coinalyze")


async def fetch_coindesk_orderbook(
    *,
    symbol: str,
    api_key: str,
    depth: int = 50,
) -> dict[str, Any]:
    headers = {"X-API-KEY": api_key}
    params = {"symbol": symbol, "depth": depth}
    data = await async_fetch_json(_COINDESK_ORDERBOOK, params=params, headers=headers, timeout=10.0)
    if isinstance(data, dict):
        return data
    raise ValueError("Unexpected response from Coindesk orderbook")


def _extract_volume_funding(snapshot: dict[str, Any]) -> tuple[float | None, float | None]:
    data = snapshot.get("data") if isinstance(snapshot, dict) else None
    if isinstance(data, dict):
        volume = data.get("volume24h") or data.get("volume")
        funding = data.get("fundingRate")
        try:
            vol_value = float(volume) if volume is not None else None
        except Exception:
            vol_value = None
        try:
            funding_value = float(funding) if funding is not None else None
        except Exception:
            funding_value = None
        return vol_value, funding_value
    return None, None


def _compute_orderbook_imbalance(orderbook: dict[str, Any]) -> float | None:
    if not isinstance(orderbook, dict):
        return None
    bids = orderbook.get("bids")
    asks = orderbook.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list):
        return None
    def _side_total(side: list[Any]) -> float:
        total = 0.0
        for level in side:
            if isinstance(level, list | tuple) and len(level) >= 2:
                try:
                    qty = float(level[1])
                except Exception:
                    qty = 0.0
            elif isinstance(level, dict):
                try:
                    qty = float(level.get("volume") or 0.0)
                except Exception:
                    qty = 0.0
            else:
                qty = 0.0
            total += qty
        return total
    bid_total = _side_total(bids)
    ask_total = _side_total(asks)
    denom = bid_total + ask_total
    if denom <= 0:
        return None
    return (bid_total - ask_total) / denom


def _compute_whale_pressure(events: Iterable[dict[str, Any]] | None) -> float | None:
    if not events:
        return None
    total = 0.0
    count = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        direction = event.get("direction") or event.get("side")
        magnitude = event.get("value_usd") or event.get("value")
        try:
            amount = float(magnitude) if magnitude is not None else None
        except Exception:
            continue
        if amount is None:
            continue
        if direction in {"out", "sell", "withdrawal"}:
            total -= amount
        else:
            total += amount
        count += 1
    if count == 0:
        return None
    return max(-1.0, min(1.0, total / (abs(total) + 1e-6)))


async def score_asset(
    symbol: str,
    *,
    coinalyze_market: str | None = None,
    coinalyze_api_key: str | None = None,
    coindesk_symbol: str | None = None,
    coindesk_api_key: str | None = None,
    whale_events: Iterable[dict[str, Any]] | None = None,
    rumour_records: Iterable[dict[str, Any]] | None = None,
    days: int = 30,
) -> ScoreReport:
    norm = symbol.upper()
    coingecko_id = get_coingecko_id(norm)
    if not coingecko_id:
        raise ValueError(f"Unknown CoinGecko id for symbol {symbol}")

    market_chart = await fetch_coingecko_market_chart(coingecko_id=coingecko_id, days=days)
    volatility = _compute_volatility(market_chart["price"]) if "price" in market_chart else None

    volume_ratio = None
    funding_rate = None
    snapshot: dict[str, Any] | None = None
    if coinalyze_market and coinalyze_api_key:
        snapshot = await fetch_coinalyze_snapshot(market=coinalyze_market, api_key=coinalyze_api_key)
        volume, funding_rate = _extract_volume_funding(snapshot)
        if volume is not None and volatility is not None:
            # Use simple proxy: volume scaled by volatility
            volume_ratio = volume / max(volatility, 1e-6)

    orderbook_data: dict[str, Any] | None = None
    if coindesk_symbol and coindesk_api_key:
        orderbook_data = await fetch_coindesk_orderbook(symbol=coindesk_symbol, api_key=coindesk_api_key)
    imbalance = _compute_orderbook_imbalance(orderbook_data) if orderbook_data else None

    whale_pressure = _compute_whale_pressure(whale_events)
    rumour_intensity, rumour_signal, rumour_confidence = _compute_rumour_intensity(rumour_records, norm)

    components = ScoreComponents(
        volatility_annualized=volatility,
        volume_funding_ratio=volume_ratio,
        funding_rate=funding_rate,
        orderbook_imbalance=imbalance,
        whale_pressure=whale_pressure,
        rumour_intensity_index=rumour_intensity,
    )

    weights = {
        "volatility": 0.25,
        "volume": 0.2,
        "funding": 0.15,
        "orderbook": 0.15,
        "whale": 0.15,
        "rumour": 0.1,
    }
    score = 0.0
    score += weights["volatility"] * _normalize_volatility(volatility)
    score += weights["volume"] * _normalize_volume_ratio(volume_ratio)
    score += weights["funding"] * _normalize_funding_rate(funding_rate)
    score += weights["orderbook"] * _normalize_orderbook_imbalance(imbalance)
    score += weights["whale"] * _normalize_whale_pressure(whale_pressure)
    score += weights["rumour"] * _normalize_rumour_intensity(rumour_intensity)

    if score >= 0.7:
        strategy = "Bullish bias: consider scaling in with tight risk controls."
    elif score >= 0.4:
        strategy = "Neutral: maintain hedged exposure and monitor funding/volume shifts."
    else:
        strategy = "Cautious: reduce leverage, wait for confirmation from flow metrics."
    if rumour_signal == "buy_rumour":
        strategy += " Narrative momentum suggests potential pre-event positioning."
    elif rumour_signal == "sell_news":
        strategy += " Narrative momentum fading; tighten trailing stops."

    context: dict[str, Any] = {
        "coinalyze_snapshot": snapshot,
        "orderbook": orderbook_data,
        "data_points": len(market_chart),
    }
    if rumour_signal:
        context["rumour_signal"] = rumour_signal
    if rumour_confidence is not None:
        context["rumour_confidence"] = round(rumour_confidence, 3)
    if rumour_intensity is not None:
        context["rumour_intensity"] = round(rumour_intensity, 4)
    if whale_pressure is not None and rumour_intensity is not None:
        composite = (
            _normalize_whale_pressure(whale_pressure) + _normalize_rumour_intensity(rumour_intensity)
        ) / 2.0
        context.setdefault("composite_scores", {})["rumour_whale"] = round(composite, 4)
        if composite >= 0.8:
            context.setdefault("alerts", []).append("narrative_whale_alignment")
        elif composite <= 0.2:
            context.setdefault("alerts", []).append("narrative_whale_divergence")

    return ScoreReport(
        symbol=norm,
        coingecko_id=coingecko_id,
        components=components,
        score=round(score, 4),
        strategy=strategy,
        context=context,
    )


__all__ = [
    "ScoreComponents",
    "ScoreReport",
    "fetch_coingecko_market_chart",
    "fetch_coinalyze_snapshot",
    "fetch_coindesk_orderbook",
    "score_asset",
]

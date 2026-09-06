#!/usr/bin/env python3
"""
Génère une analyse structurée pour un actif (Option 2-ready), en consommant les collectors existants
et quelques requêtes additionnelles (RSI, profondeur). Sortie: Markdown + bloc JSON strict.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sqlite3
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.assets import get_coingecko_id as resolve_coingecko_id
from pipeline.assets import get_symbol_metadata, to_perp_symbol
from pipeline.collectors.derivatives import (
    fetch_bybit_funding,
    fetch_bybit_long_short_ratio,
    fetch_bybit_oi,
)
from pipeline.collectors.market import fetch_market
from pipeline.collectors.onchain import fetch_sopr
from pipeline.collectors.orderbook import fetch_orderbook_summary
from pipeline.http import async_fetch_json
from pipeline.storage.sqlite_adapter import get_default_db_path
from pipeline.technical_indicators import fetch_binance_ohlc


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _fmt_num(value: Any) -> str:
    val = _safe_float(value)
    if val is None:
        return "N/A"
    abs_val = abs(val)
    if abs_val >= 1e9:
        return f"{val/1e9:.2f}B"
    if abs_val >= 1e6:
        return f"{val/1e6:.2f}M"
    if abs_val >= 1e3:
        return f"{val/1e3:.2f}K"
    if abs_val >= 1:
        return f"{val:.2f}"
    return f"{val:.4f}"


def _fmt_pct(value: Any) -> str:
    val = _safe_float(value)
    if val is None:
        return "N/A"
    prefix = "+" if val > 0 else ""
    return f"{prefix}{val:.2f}%"


def _pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return ((new - old) / old) * 100


def _compute_rsi(series: pd.Series, length: int = 14) -> float | None:
    clean = series.dropna()
    if clean.size <= length:
        return None
    delta = clean.diff().dropna()
    if delta.empty:
        return None
    gains = delta.clip(lower=0)
    losses = (-delta.clip(upper=0)).astype(float)
    avg_gain = gains.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / length, adjust=False).mean()
    zero_loss_mask = avg_loss == 0
    avg_loss = avg_loss.replace(0.0, pd.NA)
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    if isinstance(zero_loss_mask, pd.Series):
        rsi = rsi.where(~zero_loss_mask, 100.0)
    valid = rsi.dropna()
    if valid.empty:
        return None
    return float(valid.iloc[-1])


def _resolve_binance_symbol(symbol: str | None) -> str | None:
    if not symbol:
        return None
    base = symbol.upper()
    meta = get_symbol_metadata(base)
    pairs = (meta or {}).get("binance_pairs") if meta else None
    if pairs:
        return str(pairs[0])
    if base.endswith("USDT"):
        return base
    return to_perp_symbol(base, quote="USDT")


def _resolve_bybit_symbol(symbol: str | None) -> str | None:
    if not symbol:
        return None
    base = symbol.upper()
    meta = get_symbol_metadata(base)
    pairs = (meta or {}).get("bybit_pairs") if meta else None
    if pairs:
        return str(pairs[0])
    if base.endswith("USDT"):
        return base
    return f"{base}USDT"


def _resolve_coingecko(symbol: str, override: str | None) -> str | None:
    if override:
        return override
    meta = get_symbol_metadata(symbol)
    ids = (meta or {}).get("coingecko_ids") if meta else None
    if ids:
        return str(ids[0])
    return resolve_coingecko_id(symbol)


def _collect_rsi(symbol: str | None, length: int = 14) -> dict[str, Any]:
    pair = _resolve_binance_symbol(symbol)
    if not pair:
        return {}
    try:
        df = fetch_binance_ohlc(symbol=pair, interval="1h", limit=length * 6)
    except Exception:
        return {}
    if df is None or df.empty or "close" not in df.columns:
        return {}
    value = _compute_rsi(df["close"], length=length)
    if value is None:
        return {}
    return {"rsi": value, "pair": pair, "source": "binance_spot"}


def _rsi_note(value: float | None) -> str:
    if value is None:
        return "N/A"
    if value >= 70:
        bucket = "sur-achat"
    elif value >= 60:
        bucket = "haussier"
    elif value >= 45:
        bucket = "neutre"
    elif value >= 30:
        bucket = "faible"
    else:
        bucket = "sur-vente"
    return f"RSI {value:.1f} ({bucket})"


def _format_orderbook_zone(zone: dict[str, Any] | None, total: float | None) -> str:
    if not zone:
        return "N/A"
    total_txt = _fmt_num(total)
    top = _safe_float(zone.get("top"))
    tail = _safe_float(zone.get("tail"))
    levels = zone.get("levels", 0)
    if top is not None and tail is not None:
        lower = min(top, tail)
        upper = max(top, tail)
        return f"{total_txt} ({levels} lvls, {lower:.2f}-{upper:.2f})"
    return f"{total_txt} ({levels} lvls)"


def _format_orderbook_line(summary: dict[str, Any] | None) -> tuple[str, str, str]:
    if not summary:
        return "N/A", "N/A", "Carte d’ordres: N/A"
    bids = _format_orderbook_zone(summary.get("bids_zone"), summary.get("bid_total_quote"))
    asks = _format_orderbook_zone(summary.get("asks_zone"), summary.get("ask_total_quote"))
    spread = _safe_float(summary.get("spread"))
    spread_pct = _safe_float(summary.get("spread_pct"))
    if spread is not None and spread_pct is not None:
        spread_txt = f"Spread: {_fmt_num(spread)} ({_fmt_pct(spread_pct)})"
    elif spread is not None:
        spread_txt = f"Spread: {_fmt_num(spread)}"
    elif spread_pct is not None:
        spread_txt = f"Spread: {_fmt_pct(spread_pct)}"
    else:
        spread_txt = "Spread: N/A"
    line = f"Bid: {bids} | Ask: {asks} | {spread_txt}"
    return bids, asks, line


def _lsr_note(record: dict[str, Any] | None) -> tuple[str, float | None, float | None]:
    if not record:
        return "Bybit L/S: N/A", None, None
    value = record.get("value") if isinstance(record, dict) else None
    if not isinstance(value, dict):
        return "Bybit L/S: N/A", None, None
    buy = _safe_float(value.get("buy_ratio"))
    sell = _safe_float(value.get("sell_ratio"))
    if buy is None and sell is None:
        return "Bybit L/S: N/A", None, None
    if buy is None:
        buy = 0.0
    if sell is None:
        sell = 0.0
    total = buy + sell
    if total > 0:
        buy_pct = buy / total * 100
        sell_pct = sell / total * 100
    else:
        buy_pct = buy
        sell_pct = sell
    diff = buy_pct - sell_pct
    if diff > 5:
        bias = "dominance longs"
    elif diff < -5:
        bias = "dominance shorts"
    else:
        bias = "équilibre"
    note = f"Bybit L/S: {buy_pct:.2f}% / {sell_pct:.2f}% ({bias})"
    return note, buy_pct, sell_pct


def _sopr_note(value: float | None) -> tuple[str, float | None]:
    if value is None:
        return "SOPR: N/A", None
    if value >= 1.02:
        bias = "prise de profit"
    elif value <= 0.98:
        bias = "capitulation"
    else:
        bias = "neutre"
    return f"SOPR: {value:.2f} ({bias})", value


async def _fetch_market_safe(cg_id: str | None, symbol: str) -> dict[str, Any]:
    try:
        target = cg_id or symbol
        data = fetch_market(target)
        if asyncio.iscoroutine(data):  # type: ignore
            data = await data  # type: ignore
        return data or {}
    except Exception:
        return {}


async def _fetch_oi_deltas(bybit_symbol: str) -> dict[str, Any]:
    try:
        data = await async_fetch_json(
            "https://api.bybit.com/v5/market/open-interest",
            params={
                "category": "linear",
                "symbol": bybit_symbol.upper(),
                "intervalTime": "1h",
                "limit": 25,
            },
            timeout=10,
        )
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    entries = data.get("result", {}).get("list", [])
    if not isinstance(entries, list) or not entries:
        return {}
    latest = _safe_float(entries[-1].get("openInterest"))
    if latest is None:
        return {}
    prev = _safe_float(entries[-2].get("openInterest")) if len(entries) >= 2 else None
    day = _safe_float(entries[-25].get("openInterest")) if len(entries) >= 25 else None
    return {
        "oi_change_1h_pct": _pct_change(latest, prev),
        "oi_change_24h_pct": _pct_change(latest, day),
    }


async def _fetch_derivatives_safe(bybit_symbol: str | None) -> dict[str, Any]:
    if not bybit_symbol:
        return {}
    oi_task = fetch_bybit_oi(bybit_symbol)
    funding_task = fetch_bybit_funding(bybit_symbol)
    deltas_task = _fetch_oi_deltas(bybit_symbol)
    oi_res, funding_res, delta_res = await asyncio.gather(
        oi_task,
        funding_task,
        deltas_task,
        return_exceptions=True,
    )
    out: dict[str, Any] = {}
    if not isinstance(oi_res, Exception) and isinstance(oi_res, dict):
        out["oi_usd"] = oi_res.get("value")
        out["oi_timestamp"] = oi_res.get("timestamp")
        out["oi_source"] = oi_res.get("source")
    if not isinstance(funding_res, Exception) and isinstance(funding_res, dict):
        out["funding_rate"] = funding_res.get("value")
        out["funding_timestamp"] = funding_res.get("timestamp")
        out["funding_source"] = funding_res.get("source")
    if not isinstance(delta_res, Exception) and isinstance(delta_res, dict):
        out["oi_change_1h_pct"] = delta_res.get("oi_change_1h_pct")
        out["oi_change_24h_pct"] = delta_res.get("oi_change_24h_pct")
    return out


async def _fetch_orderbook_safe(symbol: str | None) -> dict[str, Any]:
    if not symbol:
        return {}
    try:
        data = await fetch_orderbook_summary(symbol, depth=50, top_n=15)
        return data or {}
    except Exception:
        return {}


def _fetch_liquidations_24h(db_path: str, symbol: str | None) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {}
    try:
        conn = sqlite3.connect(str(path))
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bybit_liquidations'"
        )
        if not cur.fetchone():
            conn.close()
            return {}
        cutoff = int((datetime.now(UTC) - timedelta(hours=24)).timestamp() * 1000)
        params: list[Any] = [cutoff]
        clause = ""
        if symbol:
            clause = " AND symbol = ?"
            params.append(symbol.upper())
        cur.execute(
            f"""
            SELECT
              SUM(qty_usd) as total,
              SUM(CASE WHEN side='BUY' THEN qty_usd ELSE 0 END) as long_total,
              SUM(CASE WHEN side='SELL' THEN qty_usd ELSE 0 END) as short_total,
              COUNT(*) as events
            FROM bybit_liquidations
            WHERE time >= ?{clause}
            """,
            params,
        )
        row = cur.fetchone() or (None, None, None, None)
        conn.close()
        total, long_total, short_total, events = row
        if total is None and events is None:
            return {}
        return {
            "liq_24h_total_usd": float(total or 0.0),
            "liq_24h_long_usd": float(long_total or 0.0),


            "liq_24h_short_usd": float(short_total or 0.0),
            "liq_24h_events": int(events or 0),
        }
    except Exception:
        return {}


async def _fetch_flux_metrics(symbol: str, bybit_symbol: str | None) -> dict[str, Any]:
    coros: list[Awaitable[Any]] = []
    wants_lsr = bool(bybit_symbol)
    wants_sopr = symbol in {"BTC", "ETH"}
    if wants_lsr and bybit_symbol:
        coros.append(fetch_bybit_long_short_ratio(bybit_symbol))
    if wants_sopr:
        coros.append(fetch_sopr(symbol))
    results: list[Any] = []
    if coros:
        results = await asyncio.gather(*coros, return_exceptions=True)
    result: dict[str, Any] = {}
    idx = 0
    if wants_lsr:
        lsr_value: Any = None
        if idx < len(results):
            candidate = results[idx]
            idx += 1
            if not isinstance(candidate, Exception):
                lsr_value = candidate
        if isinstance(lsr_value, dict):
            result["lsr"] = lsr_value
    if wants_sopr:
        sopr_value: Any = None
        if idx < len(results):
            candidate = results[idx]
            idx += 1
            if not isinstance(candidate, Exception):
                sopr_value = candidate
        if isinstance(sopr_value, dict):
            result["sopr"] = sopr_value
    return result


def _render_markdown(
    symbol: str,
    timestamp: datetime,
    market: dict[str, Any],
    deriv: dict[str, Any],
    liq: dict[str, Any],
    flux_note: str,
    momentum_note: str,
    orderbook_line: str,
    json_payload: dict[str, Any],
) -> str:
    ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    price = market.get("price")
    vol = market.get("volume_24h")
    mc = market.get("marketcap")
    price_change_pct = market.get("price_change_pct_24h")
    volume_change_pct = market.get("volume_change_pct_24h")
    funding = deriv.get("funding_rate")
    funding_pct = None if funding is None else funding * 100
    oi_value = deriv.get("oi_usd")
    oi_delta_1h = deriv.get("oi_change_1h_pct")
    oi_delta_24h = deriv.get("oi_change_24h_pct")
    liq_total = liq.get("liq_24h_total_usd")
    liq_long = liq.get("liq_24h_long_usd")
    liq_short = liq.get("liq_24h_short_usd")

    lines: list[str] = []
    lines.append(f"# Analyse {symbol} — {ts_str}\n")
    lines.append("## 1. Contexte\n")
    lines.append(f"- Actif: {symbol}")
    lines.append(f"- Timestamp: {ts_str}\n")

    lines.append("## 2. Capitalisation & volumes\n")
    lines.append(f"- Capitalisation: {_fmt_num(mc)}")
    lines.append(
        f"- Volume 24h: {_fmt_num(vol)} | Δ24h: {_fmt_pct(volume_change_pct)}\n"
    )

    lines.append("## 3. Technique (prix/élan)\n")
    lines.append(f"- Prix actuel: {_fmt_num(price)} | Δ24h: {_fmt_pct(price_change_pct)}")
    lines.append(f"- Momentum/RSI: {momentum_note}\n")

    lines.append("## 4. Dérivés (OI / funding)\n")
    lines.append(
        f"- OI ($): {_fmt_num(oi_value)} | Δ1h: {_fmt_pct(oi_delta_1h)} | Δ24h: {_fmt_pct(oi_delta_24h)}"
    )
    lines.append(f"- Funding: {_fmt_pct(funding_pct)}\n")

    lines.append("## 5. Flux & liquidations\n")
    lines.append(f"- Liquidations 24h (total): {_fmt_num(liq_total)}")
    lines.append(f"  - Longs: {_fmt_num(liq_long)} | Shorts: {_fmt_num(liq_short)}\n")
    lines.append(f"- Indices baleines / flux: {flux_note}\n")

    lines.append("## 6. Profondeur / ordres\n")
    lines.append(f"- Carte d’ordres: {orderbook_line}\n")

    lines.append("## 7. Scénarios 24–72h (qualitatif)\n")
    lines.append(
        "- Hausse: breakout avec volumes > moyenne, confirmations sur dérivés (funding modéré, OI en hausse graduelle)"
    )
    lines.append("- Range: compression de volatilité; rotations sectorielles; invalidation si perte du support clé")
    lines.append("- Baisse: funding qui s’emballe + OI↑ rapide sans progression spot; spikes de liquidations longs\n")

    lines.append("## 8. Plan de risque\n")
    lines.append("- Invalidations clés: supports proches | échecs de breakout avec volumes faibles")
    lines.append("- Signaux à surveiller: funding, OI, volumes, liquidations\n")

    lines.append("## 9. Données (JSON)\n")
    lines.append("```json")
    lines.append(json.dumps(json_payload, indent=2, sort_keys=True, ensure_ascii=False))
    lines.append("```")
    lines.append("\n— Lecture informative, pas un conseil financier.\n")
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Génère une analyse structurée pour un actif crypto")
    parser.add_argument("--symbol", required=True, help="Ticker ex: BTC, ETH, RENDER")
    parser.add_argument("--coingecko-id", default=None, help="Override id CoinGecko (ex: bitcoin)")
    parser.add_argument("--bybit-symbol", default=None, help="Override symbole Bybit (ex: BTCUSDT)")
    parser.add_argument("--db", default=get_default_db_path(), help="Chemin base SQLite liquidations")
    parser.add_argument(
        "--out",
        default=None,
        help="Chemin de sortie .md (défaut: exports/analysis/<SYMBOL>_analysis.md)",
    )
    args = parser.parse_args()

    symbol = args.symbol.strip().upper()
    cg_id = _resolve_coingecko(symbol, args.coingecko_id)
    if not cg_id:
        raise SystemExit(
            f"Impossible de résoudre l'identifiant CoinGecko pour {symbol}. "
            "Fournissez --coingecko-id explicitement."
        )
    bybit_symbol = args.bybit_symbol or _resolve_bybit_symbol(symbol)
    binance_symbol = _resolve_binance_symbol(symbol)
    out_path = Path(args.out) if args.out else Path("exports/analysis") / f"{symbol}_analysis.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    market_task = _fetch_market_safe(cg_id, symbol)
    derivatives_task = _fetch_derivatives_safe(bybit_symbol)
    orderbook_task = _fetch_orderbook_safe(binance_symbol)
    flux_task = _fetch_flux_metrics(symbol, bybit_symbol)
    rsi_task = asyncio.to_thread(_collect_rsi, binance_symbol)

    market, derivatives, orderbook_summary, flux_data, rsi_data = await asyncio.gather(
        market_task,
        derivatives_task,
        orderbook_task,
        flux_task,
        rsi_task,
    )
    liq = _fetch_liquidations_24h(args.db, bybit_symbol and bybit_symbol.replace("USDT", ""))

    bids_zone, asks_zone, orderbook_line = _format_orderbook_line(orderbook_summary)
    momentum_note = _rsi_note(rsi_data.get("rsi")) if isinstance(rsi_data, dict) else "N/A"
    lsr_line, lsr_buy_pct, lsr_sell_pct = _lsr_note(flux_data.get("lsr")) if isinstance(flux_data, dict) else (
        "Bybit L/S: N/A",
        None,
        None,
    )
    sopr_record = flux_data.get("sopr") if isinstance(flux_data, dict) else None
    sopr_value = _safe_float(sopr_record.get("value")) if isinstance(sopr_record, dict) else None
    sopr_line, sopr_numeric = _sopr_note(sopr_value)
    flux_components = [part for part in (lsr_line, sopr_line) if part]
    flux_note = " | ".join(flux_components)

    json_payload = {
        "symbol": symbol,
        "price": market.get("price"),
        "price_change_24h_pct": market.get("price_change_pct_24h"),
        "market_cap_usd": market.get("marketcap"),
        "volume_24h_usd": market.get("volume_24h"),
        "volume_change_24h_pct": market.get("volume_change_pct_24h"),
        "funding_rate": derivatives.get("funding_rate"),
        "oi_usd": derivatives.get("oi_usd"),
        "oi_change_1h_pct": derivatives.get("oi_change_1h_pct"),
        "oi_change_24h_pct": derivatives.get("oi_change_24h_pct"),
        "liquidations_24h_total_usd": liq.get("liq_24h_total_usd"),
        "liquidations_24h_long_usd": liq.get("liq_24h_long_usd"),
        "liquidations_24h_short_usd": liq.get("liq_24h_short_usd"),
        "long_short_ratio_buy_pct": lsr_buy_pct,
        "long_short_ratio_sell_pct": lsr_sell_pct,
        "onchain_sopr": sopr_numeric,
        "flux_note": flux_note,
        "orderbook": {
            "bids_zone": bids_zone,
            "asks_zone": asks_zone,
        },
    }

    markdown = _render_markdown(
        symbol,
        datetime.now(UTC),
        market,
        derivatives,
        liq,
        flux_note,
        momentum_note,
        orderbook_line,
        json_payload,
    )
    out_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote analysis to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

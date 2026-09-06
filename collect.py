"""
Collecteur minimal (prod-safe) pour agréger quelques métriques publiques et exporter en JSON/CSV/Parquet/SQLite.

Exemples:
  python collect.py --sources coingecko --symbols BTC,ETH --export data/metrics.json
  python collect.py --sources coingecko,bybit --symbols BTC,ETH --export data/metrics.json --csv data/metrics.csv
  python collect.py --mock --symbols BTC,ETH,SOL --export data/metrics.json

Notes:
- Ne nécessite aucune clé API pour CoinGecko (gratuit, endpoints publics), Bybit (public), mais gère les erreurs réseau.
- L'option --mock permet un run hors-ligne.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

from pipeline.assets import get_coingecko_id

try:
    from pipeline.storage_utils import save_to_csv, save_to_parquet, save_to_sqlite
except Exception:  # pragma: no cover
    # Fallbacks neutres si import échoue (environnements ultra-minimaux)
    def save_to_csv(rows: list[dict[str, Any]], path: str) -> None:
        import csv

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fieldnames = sorted({k for row in rows for k in row})
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in rows:
                w.writerow(row)

    def save_to_parquet(rows: list[dict[str, Any]], path: str) -> None:
        raise RuntimeError("Parquet indisponible (pyarrow/pandas manquant)")

    def save_to_sqlite(rows: list[dict[str, Any]], path: str, table: str = "metrics") -> None:
        import sqlite3

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        conn = sqlite3.connect(path)
        try:
            if not rows:
                return
            cols = sorted({k for r in rows for k in r})
            placeholders = ",".join(["?"] * len(cols))
            colspec = ",".join([f"[{c}]" for c in cols])
            conn.execute(f"CREATE TABLE IF NOT EXISTS [{table}] ({colspec})")
            conn.executemany(
                f"INSERT INTO [{table}] ({colspec}) VALUES ({placeholders})",
                [[r.get(c) for c in cols] for r in rows],
            )
            conn.commit()
        finally:
            conn.close()


@dataclass
class Metric:
    timestamp: int
    symbol: str
    source: str
    metric: str
    value: float | int | str
    extra: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        base = {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "source": self.source,
            "metric": self.metric,
            "value": self.value,
        }
        if self.extra:
            base.update({f"extra_{k}": v for k, v in self.extra.items()})
        return base


def now_ts() -> int:
    return int(time.time())


async def fetch_coingecko(symbols: list[str]) -> list[Metric]:
    ids: list[str] = []
    id_to_symbol: dict[str, str] = {}
    for symbol in symbols:
        cg_id = get_coingecko_id(symbol)
        if not cg_id:
            continue
        ids.append(cg_id)
        id_to_symbol[cg_id] = symbol
    if not ids:
        return []
    url = (
        "https://api.coingecko.com/api/v3/simple/price?"
        f"ids={','.join(ids)}&vs_currencies=usd&include_24hr_change=true"
    )
    ts = now_ts()
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    out: list[Metric] = []
    for cid, obj in (data or {}).items():
        sym = id_to_symbol.get(cid)
        if not sym:
            continue
        price = obj.get("usd")
        chg = obj.get("usd_24h_change")
        if price is not None:
            out.append(Metric(ts, sym, "coingecko", "price_usd", float(price)))
        if chg is not None:
            out.append(Metric(ts, sym, "coingecko", "change_24h_pct", float(chg)))
    return out


async def fetch_bybit(symbols: list[str]) -> list[Metric]:
    # Minimal: tentative de funding rate public (sans clé). En cas d'échec: ignore.
    # Doc indicative: https://api.bybit.com/v5/market/funding/history
    # On reste volontairement simple et résilient.
    ts = now_ts()
    out: list[Metric] = []
    base = "https://api.bybit.com"
    for sym in symbols:
        try:
            inst = f"{sym}USDT"
            url = f"{base}/v5/market/funding/history?category=linear&symbol={inst}&limit=1"
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=15)
                r.raise_for_status()
                data = r.json()
            arr = (((data or {}).get("result") or {}).get("list")) or []
            if arr:
                funding = arr[0].get("fundingRate")
                if funding is not None:
                    out.append(Metric(ts, sym, "bybit", "funding_rate", float(funding)))
        except Exception:
            continue
    return out


def build_mock(symbols: list[str]) -> list[Metric]:
    ts = now_ts()
    out: list[Metric] = []
    for i, sym in enumerate(symbols):
        out.append(Metric(ts, sym, "mock", "price_usd", 10000 + 123 * i))
        out.append(Metric(ts, sym, "mock", "change_24h_pct", (-1) ** i * 2.5))
        out.append(Metric(ts, sym, "mock", "funding_rate", 0.01 * ((i % 3) - 1)))
        out.append(Metric(ts, sym, "mock", "sentiment", "neutre"))
    return out


async def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Collecteur minimal prod-safe")
    p.add_argument(
        "--sources", type=str, default="coingecko", help="sources séparées par des virgules (coingecko,bybit)"
    )
    p.add_argument("--symbols", type=str, default="BTC,ETH", help="symboles séparés par des virgules")
    p.add_argument("--export", type=str, required=True, help="chemin du JSON de sortie (metrics)")
    p.add_argument("--csv", type=str, default="", help="optionnel: chemin CSV")
    p.add_argument("--parquet", type=str, default="", help="optionnel: chemin Parquet")
    p.add_argument("--sqlite", type=str, default="", help="optionnel: chemin SQLite")
    p.add_argument("--sqlite-table", type=str, default="metrics", help="nom de table SQLite")
    p.add_argument("--mock", action="store_true", help="exécute hors-ligne avec données fictives")
    args = p.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    rows: list[dict[str, Any]] = []

    if args.mock:
        metrics = build_mock(symbols)
        rows.extend(m.as_dict() for m in metrics)
    else:
        srcs = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
        # Collectes parallélisables (facile): on séquence pour simplicité prodsafe
        if "coingecko" in srcs:
            metrics = await fetch_coingecko(symbols)
            rows.extend(m.as_dict() for m in metrics)
        if "bybit" in srcs:
            metrics = await fetch_bybit(symbols)
            rows.extend(m.as_dict() for m in metrics)

    # Sauvegardes
    os.makedirs(os.path.dirname(args.export) or ".", exist_ok=True)
    with open(args.export, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    if args.csv:
        save_to_csv(rows, args.csv)
    if args.parquet:
        save_to_parquet(rows, args.parquet)
    if args.sqlite:
        save_to_sqlite(rows, args.sqlite, table=args.sqlite_table)

    print(json.dumps({"status": "ok", "records": len(rows), "export": args.export}))
    return 0


if __name__ == "__main__":
    try:
        import asyncio

        raise SystemExit(asyncio.run(main(sys.argv[1:])))
    except KeyboardInterrupt:
        raise SystemExit(130) from None

import asyncio
import glob
import sqlite3

from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter
from pipeline.http_wrappers import endpoint_label


def test_endpoint_label_cardinality():
    # Générer 50 URLs avec variations de query, versions et segments aléatoires
    base_urls = [
        "https://api.coingecko.com/api/v3/coins/bitcoin?x=1",
        "https://api.coingecko.com/api/v3/coins/ethereum?y=2",
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin",
        "https://api.binance.com/api/v3/depth?symbol=BTCUSDT",
        "https://api.binance.com/api/v3/depth?symbol=ETHUSDT",
        "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
        "https://api.llama.fi/protocols",
        "https://www.coingecko.com/api/v3/ping",
        "https://api.coinmarketcap.com/v1/cryptocurrency/listings/latest",
        "https://api.coinmarketcap.com/v3/cryptocurrency/quotes/latest?id=1",
    ]
    # Ajouter variations synthétiques
    base_urls += [f"https://api.coingecko.com/api/v3/coins/randomtoken{i}?foo=bar&v={i}" for i in range(40)]
    labels = {endpoint_label(u) for u in base_urls}
    # On s'attend à une forte déduplication: coingecko/coins, coingecko/simple, binance/depth, binance/ticker, llama/protocols, coingecko/ping, coinmarketcap/cryptocurrency => ~7-8
    assert len(labels) < 15, f"Cardinalité trop élevée: {len(labels)} labels = {labels}"  # seuil large pour robustesse


async def _write_events(writer: BybitLiquidationsWriter, events):
    for ev in events:
        await writer.write_record(ev)
    await writer.flush()


def test_bybit_hourly_aggregation_and_parquet_disabled(tmp_path):
    db_path = tmp_path / "liq.db"
    parquet_dir = tmp_path / "parquet"
    writer = BybitLiquidationsWriter(
        db=str(db_path), parquet_dir=str(parquet_dir), flush_size=10, parquet_enabled=False
    )

    # Deux events même heure/symbol/side
    hour_ts = 1700000000 * 1000  # arbitraire en ms
    events = [
        {"symbol": "BTCUSDT", "side": "Buy", "price": 50000, "size": 10, "updatedTime": hour_ts},
        {"symbol": "BTCUSDT", "side": "Buy", "price": 50500, "size": 2, "updatedTime": hour_ts + 30_000},  # même heure
    ]
    asyncio.run(_write_events(writer, events))

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT symbol, side, total_qty_usd, events_count FROM bybit_liquidations_hourly")
    rows = cur.fetchall()
    assert len(rows) == 1, rows
    sym, side, total_usd, count = rows[0]
    # total_qty_usd attendu = 50000*10 + 50500*2 = 500000 + 101000 = 601000
    assert sym == "BTCUSDT" and side == "BUY"
    assert abs(total_usd - 601000) < 0.01
    assert count == 2

    # Vérifie qu'aucun fichier parquet n'est écrit (parquet_enabled=False)
    parquet_files = glob.glob(str(parquet_dir / "**" / "*.parquet"), recursive=True)
    assert parquet_files == []

    conn.close()

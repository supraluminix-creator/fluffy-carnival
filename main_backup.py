import asyncio
import os
from datetime import datetime
from tabulate import tabulate  # type: ignore[import-untyped]
from prometheus_client import start_http_server
import structlog

from pipeline.collectors.market import fetch_macro
from pipeline.collectors.defillama import fetch_defillama_tvl
from pipeline.collectors.onchain import fetch_txcount, fetch_hashrate, fetch_sopr
from pipeline.collectors.derivatives import fetch_bybit_oi, fetch_bybit_long_short_ratio
from pipeline.collectors.sentiment import fetch_fear_greed

EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

EXPORT_FIELDS = [
    "timestamp",
    "asset",
    "symbol",
    "chain",
    "metric_name",
    "value",
    "source",
    "confidence_score"
]

def safe_print_table(title, data, headers):
    print(f"\n[{title}]")
    try:
        print(tabulate(data, headers=headers, tablefmt="psql"))
    except Exception:
        print("Aucune donnée ou erreur de format.")

def export_csv(data: list, filename: str):
    import csv
    if not data:
        return
    # Harmonise chaque dict selon EXPORT_FIELDS
    rows = []
    for d in data:
        row = {k: d.get(k, None) for k in EXPORT_FIELDS}
        rows.append(row)
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

async def collect_all():
    cmc_api_key = os.getenv("CMC_API_KEY", "")
    etherscan_api_key = os.getenv("ETHERSCAN_API_KEY", "")

    results = []

    # Macro
    macro = await fetch_macro("bitcoin", cmc_api_key=cmc_api_key)
    safe_print_table("Macro - CoinGecko/CMC", [macro] if macro else [], "keys")
    if macro: results.append(macro)

    # DeFi
    defi = await fetch_defillama_tvl("ethereum")
    safe_print_table("DeFi - Defillama", [defi] if defi else [], "keys")
    if defi: results.append(defi)

    # On-chain
    txcount = await fetch_txcount("BTC", etherscan_api_key=etherscan_api_key)
    hashrate = await fetch_hashrate("BTC")
    sopr = await fetch_sopr("BTC")
    safe_print_table("On-chain - TxCount", [txcount] if txcount else [], "keys")
    safe_print_table("On-chain - Hashrate", [hashrate] if hashrate else [], "keys")
    safe_print_table("On-chain - SOPR", [sopr] if sopr else [], "keys")
    if txcount: results.append(txcount)
    if hashrate: results.append(hashrate)
    if sopr: results.append(sopr)

    # Dérivés - Open Interest
    bybit_oi = await fetch_bybit_oi("BTCUSDT")
    safe_print_table("Dérivés - Bybit OI", [bybit_oi] if bybit_oi else [], "keys")
    if bybit_oi: results.append(bybit_oi)

    # Dérivés - Long/Short Ratio Bybit
    bybit_lsr = await fetch_bybit_long_short_ratio("BTCUSDT")
    safe_print_table("Dérivés - Bybit Long/Short Ratio", [bybit_lsr] if bybit_lsr else [], "keys")
    if bybit_lsr: results.append(bybit_lsr)

    # Sentiment
    fg = await fetch_fear_greed()
    safe_print_table("Sentiment - Fear & Greed", [fg] if fg else [], "keys")
    if fg: results.append(fg)

    # Export CSV (consolidé + horodaté)
    export_csv(results, os.path.join(EXPORT_DIR, "latest_export.csv"))
    export_csv(results, os.path.join(EXPORT_DIR, f"pipeline_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"))

async def scheduler():
    while True:
        await collect_all()
        await asyncio.sleep(300)  # 5 min (adapter selon planning)

def setup_logging():
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

if __name__ == "__main__":
    setup_logging()
    start_http_server(8000)
    asyncio.run(scheduler())

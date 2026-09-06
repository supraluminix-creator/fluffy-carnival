# Bybit Liquidations Playbook

## Overview

The pipeline ships a prod-safe ingestion path for Bybit liquidation events. A WebSocket sidecar keeps the SQLite database (default `data/crypto.db`; override via `$env:CRYPTO_DB_PATH`) fresh, while dedicated tooling backfills historical CSV archives and audits gaps. All components follow the same observability conventions as the rest of the project (structlog JSON logs, Prometheus metrics, optional health endpoints).

## Real-Time Collector

- Module: `pipeline/collectors/bybit_ws.py`
- Entry point: `python pipeline/collectors/bybit_ws.py --symbols BTCUSDT,ETHUSDT`
- Features: exponential reconnect, configurable ping/timeout, periodic flush, Prometheus counters (`bybit_ws_*`), optional `/health` endpoint, structured logging.
- Companion smoke test: `python tools/ws_quick_probe.py --symbols BTCUSDT,ETHUSDT --duration 60`.

### Windows Task Scheduler Hint

When scheduling the collector H24 on Windows:

1. Create a task that runs `python pipeline/collectors/bybit_ws.py --symbols BTCUSDT,ETHUSDT --prometheus-port 8000 --health-port 8010` within the project virtual environment.
2. Configure “Run whether user is logged on or not” and “Restart on failure” with an exponential delay (e.g. 1, 2, 5 minutes).
3. Optional: add a second task that periodically calls `python tools/ws_quick_probe.py` to validate metrics and flush behaviour.

## Legacy Schema Upgrade

Older snapshots of the on-disk database (default `data/crypto.db`, or whatever you export via `CRYPTO_DB_PATH`) do not include the `qty_usd` column. Instantiating the writer now performs the migration automatically (column creation + hourly table rebuild). Run once before any backfill to upgrade the schema safely:

```powershell
.\.venv\Scripts\python.exe -c "from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter; w = BybitLiquidationsWriter(); w.close()"
```

Verification helpers:

```powershell
$db = if ($env:CRYPTO_DB_PATH) { $env:CRYPTO_DB_PATH } else { "data/crypto.db" }
.\.venv\Scripts\python.exe -c "import sqlite3, sys; conn=sqlite3.connect(sys.argv[1]); cur=conn.cursor(); cur.execute('PRAGMA table_info(bybit_liquidations)'); print(cur.fetchall()); conn.close()" $db
```

## Historical Backfill

- Module: `pipeline/collectors/bybit_backfill.py`
- CLI: `python tools/bybit_liq_backfill.py --symbols BTCUSDT,ETHUSDT --start 2025-02-09 --end 2025-02-10`
- Input: public CSV archives from `https://public.bybit.com/trading/<SYMBOL>/` (gzipped or plain CSV).
- Behaviour: caches downloads under `data/bybit_public/`, deduplicates events, writes to both `bybit_liquidations` and hourly aggregates, supports `--dry-run` to measure rows before writing.

Recommended workflow:

1. Identify missing days with the gap report (see below).
2. Run the backfill CLI for the relevant symbol/day range.
3. Re-run the gap report to confirm coverage.

### Automated Catch-up

- Utility: `python tools/bybit_liq_auto_backfill.py --symbols BTCUSDT,ETHUSDT --days 30`
- Behaviour: scans `bybit_liquidations` for missing days, groups contiguous gaps, and (unless `--dry-run`) invokes the backfill module for each range while reusing the CSV cache.
- Use cases: nightly dry-run to detect gaps, ad-hoc full mode after incidents, or continuous maintenance across multiple symbols.

### Auto remediation helper

To scan the last N days, compute missing windows, and trigger the backfill automatically:

```powershell
# Dry-run (report only)
.\.venv\Scripts\python.exe tools/bybit_liq_auto_backfill.py --symbols BTCUSDT,ETHUSDT --days 30 --dry-run

# Execute (downloads + writes)
.\.venv\Scripts\python.exe tools/bybit_liq_auto_backfill.py --symbols BTCUSDT,ETHUSDT,LINKUSDT,SOLUSDT,ATOMUSDT,TAOUSDT,RNDRUSDT --days 45
```

The helper groups contiguous missing days into batches (minimising HTTP calls) and re-uses the same cache/DB settings as the manual backfill. Review the JSON summary after each run to verify the number of files and rows ingested.

## Gap Audit & Archives

- Module: `tools/bybit_liq_gap_report.py`
- Purpose: compare database coverage with cached CSV files and optional archive ZIPs.
- Example: `python tools/bybit_liq_gap_report.py --symbols BTCUSDT,ETHUSDT --days 45`

Output:

```json
{
  "start": "2025-02-09",
  "end": "2025-03-25",
  "symbols": {
    "BTCUSDT": {
      "db": {
        "first_day": "2025-02-10",
        "last_day": "2025-03-25",
        "event_count": 12834
      },
      "available_days": ["2025-02-09", "2025-02-10"],
      "missing_days": ["2025-02-11"],
      "sources": {
        "cache_files": 2,
        "archive_zip": 0
      }
    }
  }
}
```

The report consumes any cached CSV (`data/bybit_public/<SYMBOL>/...`) and can also inspect nested ZIP archives (e.g. `backup_fluffy_carnival_nested.zip`). Use `--start` and `--end` for precise time windows, otherwise `--days` defaults to the last 30 days.

## Testing

Targeted pytest coverage lives in `tests/test_bybit_backfill.py`. The suite validates:

- Deduplication and SQLite inserts through `BybitLiquidationsWriter.write_many`.
- Dry-run behaviour (counts rows without writing).
- Defensive parsing (skips incomplete CSV rows).

Run locally:

```powershell
pytest tests/test_bybit_backfill.py -q
```

## Operational Checklist

1. **Before enabling H24 collection**: populate recent history via backfill; confirm with the gap report.
2. **During operation**: keep the WebSocket service running via Task Scheduler (or systemd) and monitor Prometheus metrics.
3. **After incidents**: rerun the gap report, backfill missing slots, restart the collector, and validate with `ws_quick_probe`.

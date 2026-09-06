# Pipeline Feature Catalog

## Orchestrator & Scheduler

- **Parallel collectors** via `ParallelOrchestrator` with APScheduler jitter, Prometheus metrics, and health heartbeats.
- **Jobs** defined in `scheduler/jobs.yaml`, now including:
  - `rumour_sentiment` (15m cadence) – ingests Rumour.app trending narratives when `ENABLE_RUMOUR_COLLECTOR=1`.

## Collector Suite

| Category | Collectors | Notes |
| --- | --- | --- |
| Market & Macro | `fetch_macro`, `fetch_defillama_tvl`, `fetch_txcount`, `fetch_hashrate`, `fetch_sopr` | Optional fallbacks per flag. |
| Derivatives | Bybit OI / LSR, orderbook snapshots | Includes breaker protection and metrics. |
| Sentiment | Fear & Greed index | Cached via `diskcache`. |
| Narratives | **Rumour.app** (`pipeline/collectors/rumour_collector.py`) | Scrapes trending rumours, caches JSON, exports topic/sentiment/confidence columns. |
| Whales | Etherscan balances, Hyperliquid insider | Snapshots persisted for API access. |

## Analysis & Scoring

- `pipeline/analysis/signals.py` flags long/short, sentiment, TVL, and new **narrative buy/sell** signals with explicit "NFA" disclaimers.
- `pipeline/analysis/runner.py` merges exported CSV data with `exports/rumour_latest.json` to emit composite signals and LLM prompts.
- `pipeline/scoring/probabilistic.py` introduces `rumour_intensity_index` and whale alignment alerts for Buy-the-Rumour/Sell-the-News heuristics.

## API Surface

- `/api/rumour/reports` (JSON, paginated) exposes latest narratives, keyword filtering, and optional LLM summaries powered by the existing client.
- Existing endpoints remain backward compatible; rumour columns are optional and default to safe placeholders.

## Operator Tooling

- `modules/CryptoPipelineMenu.psm1` adds a PowerShell ISE Add-ons menu and toolbar stub for quick actions (scheduler, tests, WebSocket, purge).
- Smoke scripts:
  - `scripts/test-menu.ps1` – verifies menu registration in CI.
  - `smoke_rumour.py` – lightweight collector smoke test.

## Exports & Persistence

- CSV exports include new columns `topic`, `sentiment`, and `confidence`; non-rumour collectors populate defaults.
- Rumour snapshots recorded to `exports/rumour_latest.json` and `exports/rumour_history.jsonl` for downstream tooling.

## Testing & Quality Gates

- Pytest coverage (>79%) augmented with `tests/test_rumour_collector.py`, `tests/test_api_rumour_reports.py`, and additional signal/probabilistic cases.
- Pester suite (`tests/CryptoPipelineMenu.Tests.ps1`) validates PowerShell helpers; CI workflow invokes `Invoke-Pester` alongside Pytest/Ruff.

# Rumour.app Collector

The rumour collector ingests trending narratives from [https://rumour.app/trending](https://rumour.app/trending) to complement on-chain, derivatives, and sentiment data.

## Data Model

Each rumour entry is normalised into the export schema with the following fields:

- `timestamp` – ISO 8601 (UTC) scrape time.
- `topic` – narrative headline (e.g. "AI tokens").
- `symbol` – uppercased ticker inferred from the card when present.
- `sentiment` – `positive`, `neutral`, or `negative`.
- `value` – narrative intensity (`sentiment score * confidence * mention volume`).
- `confidence` / `confidence_score` – 0.0–1.0 confidence derived from Rumour.app metadata.
- `source` – `rumour.app` or `rumour.app (mock)` when fallback data is used.

Snapshots are written to `exports/rumour_latest.json` and appended to `exports/rumour_history.jsonl` with a standard disclaimer.

## Flags and Environment Variables

| Variable | Description | Default |
| --- | --- | --- |
| `ENABLE_RUMOUR_COLLECTOR` | Opt-in toggle for the collector and scheduler job. | `0` (disabled) |
| `RUMOUR_COLLECTOR_LIMIT` | Maximum number of cards returned per run (1–50). | `10` |
| `RUMOUR_KEYWORDS` | Comma-separated filters applied during export (e.g. `ETH,BTC`). | *(empty)* |
| `ENABLE_RUMOUR_FALLBACKS` | Use mock data when Rumour.app is unreachable. | `0` |
| `RUMOUR_CACHE_TTL` | Cache TTL in seconds for `.cache_rumour.json`. | `900` |

## Integration Points

- **Scheduler**: `scheduler/jobs.yaml` contains a `rumour_sentiment` job running every 15 minutes when enabled.
- **Exports**: `pipeline/export_utils.py` now includes `topic`, `sentiment`, and `confidence` columns; existing collectors retain defaults.
- **Analysis**: `pipeline/analysis/signals.py` and `pipeline/analysis/runner.py` surface narrative buy/sell signals with an explicit "NFA" disclaimer.
- **Scoring**: `pipeline/scoring/probabilistic.py` incorporates `rumour_intensity_index` and composite alignment with whale pressure.
- **API**: `/api/rumour/reports` provides paginated rumour data and an optional LLM-generated summary.

## Limitations & Ethics

- Rumour.app content is speculative and community-sourced; treat the signals as soft indicators.
- The collector deliberately omits any private or paid endpoints.
- Disclaimers (`"NFA: Based on unverified narratives."`) are bundled with every downstream signal and API response.
- Scraping respects public pages only; avoid aggressive polling by adjusting the scheduler cadence if needed.

## Testing & Smoke Checks

- `tests/test_rumour_collector.py` mocks HTML snippets to verify parsing, caching, and fallback behaviour.
- `tests/test_api_rumour_reports.py` exercises the REST endpoint and summary generation.
- `smoke_rumour.py` runs the collector once and prints a compact summary for manual inspection.

## Extending

- Enrich the parser by mapping additional Rumour.app attributes (e.g. credibility tiers) as new export columns.
- Connect the collector to heavier analysis flows by wiring `RUMOUR_KEYWORDS` for thematic focus.
- Swap the HTML parser with an official API if Rumour.app publishes one in the future.

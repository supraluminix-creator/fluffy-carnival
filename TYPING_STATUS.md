# Typing Status (September 19, 2025)

## Overview
Global mypy run: **clean (0 errors)** across 56 source files with `ignore_missing_imports = false` globally.
Ruff RUF100: all unused `noqa` directives removed in active code (test utility duplicates excluded).
Pytest: all tests passed (green).

## Coverage Summary (from `scripts/type_health.py`)
```
legacy                         9 (47.4%)
strict                         5 (26.3%)
strict+incomplete              5 (26.3%)
```
Target next: reduce legacy bucket (< 30%) by promoting high–value collectors.

## Buckets
- strict: full `disallow_untyped_defs` and imports enforced, no incomplete defs.
- strict+incomplete: same as strict plus `disallow_incomplete_defs` enabled.
- legacy: not yet promoted (still allow untyped defs or missing stricter flags).

## Promoted Modules
| Module | Tier |
|--------|------|
| `pipeline.collectors.bybit_liquidations` | strict |
| `pipeline.collectors.bybit_ws` | strict |
| `pipeline.collectors.coingecko` | strict |
| `api.health` | strict |
| `scheduler.runner` | strict |
| `pipeline.collectors.altme` | strict+incomplete |
| `pipeline.collectors.defillama` | strict+incomplete |
| `pipeline.collectors.hashrate` | strict+incomplete |
| `pipeline.collectors.txcount` | strict+incomplete |
| `pipeline.collectors.ws` | strict+incomplete |

## Remaining Legacy Collectors (Quarantine)
| Module | Rationale / Notes | Suggested Promotion Path |
|--------|-------------------|--------------------------|
| `pipeline.collectors.base_collector` | Core base, still some dynamic attrs | Add full annotations, enable strict first |
| `pipeline.collectors.bybit_OI` | Recently partially typed; network shapes loose | Add TypedDict for API response, strict+imports |
| `pipeline.collectors.defi` | Likely varied external schema | Segment per source, add schema TypedDicts |
| `pipeline.collectors.derivatives` | Mixed endpoints | Split fetchers & unify return contract |
| `pipeline.collectors.market` | Heterogeneous macro data | Factor per provider, define normalized record type |
| `pipeline.collectors.onchain` | Multi-chain sources | Create per-chain adapter + shared models |
| `pipeline.collectors.sentiment` | External sentiment APIs | Add lightweight TypedDicts |
| `pipeline.collectors.sopr_bgeometrics` | SOPR variants, JSON parsing | Consolidate SOPR model |
| `pipeline.collectors.sopr_blockchain` | Similar to above | Merge with SOPR model |

## Immediate Wins for Next Sprint
1. Promote `bybit_OI` (already close) -> add response model & strict.
2. Consolidate SOPR collectors into unified module with a single TypedDict.
3. Extract reusable HTTP helper with typed return (`Result[T]` style) to simplify collectors.
4. Introduce `protocols.py` for Writer / Collector interfaces to reduce structural typing repetition.

## Deferred / Optional
- Generate stub packages for internal dynamic modules if needed.
- Adopt `pydantic` models only where validation adds clear ROI (avoid over-fitting).
- Add runtime schema assertion in critical collectors (e.g., liquidation events) to surface drift early.

## Lint & Tooling State
- Ruff: Core rule sets enforced (E,F,I,UP,B,SIM,PERF). Unused `noqa` cleaned.
- Mypy: Clean with strong import checking.
- Local stubs: `diskcache` extended for `clear()`; optional libs guarded.

## Command Reference
```bash
# Full type check
python -m mypy .

# Ruff (RUF100 only)
python -m ruff check --select RUF100 .

# Tests
pytest -q
```

## Change Log (This Session)
- Fixed residual mypy errors in tests & collectors.
- Removed direct method reassign in tests => used `monkeypatch.setattr`.
- Normalized websocket test servers & isolated with `mypy: ignore-errors` pragmas.
- Eliminated unused `noqa` (RUF100) across health & scheduler modules.
- Hardened `bybit_OI` return typing.
- Added comprehensive typing documentation (this file).

## Next Promotion Candidate Checklist (Template)
```text
[ ] Identify external schema & draft TypedDict
[ ] Add function & return annotations
[ ] Enable disallow_untyped_defs
[ ] Enable disallow_incomplete_defs (if stable schema)
[ ] Remove transitional ignores
[ ] Add to strict group in pyproject
```

---
Maintained by: automated typing hardening process.

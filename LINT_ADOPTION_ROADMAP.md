# Lint & Typing Adoption Roadmap

This document tracks the staged rollout of unified linting (Ruff) and progressive typing (mypy) in the project.

## Current Baseline (Phase 1)
- Single linter: Ruff (rules: E,F,I,UP,B,SIM,PERF) at line-length 120.
- Enforced scope in CI: `api/`, `scheduler/`, `main.py`.
- Per-file temporary relaxations for legacy pipeline modules in `pyproject.toml`.
- Mypy enabled for enforced scope; clean (0 errors). Global config is intentionally permissive (ignore_missing_imports=true) while core surfaces are typed incrementally.
- Flake8 removed (redundant); no dual-tool drift.

## Next Phases
### Phase 2 – Expand Ruff Enforcement
- ✅ Added `pipeline/collectors/` to enforced Ruff scope; all collectors now Ruff-clean (E,F,I,UP,B,SIM,PERF) at 120 columns.
- ✅ Addressed long lines and simplification warnings (SIM105/SIM102) in key collectors.
- ✅ Introduced Ruff formatter configuration (no external Black dependency yet).
- ⏳ Remaining: Remove per-file ignores for `pipeline/reporter.py` & `pipeline/exporter.py` after indentation and line-length refactors.
- ⏳ Optional: Evaluate enabling `RUF100` and selective `ANN` (annotation) rules once legacy modules shrink.

### Phase 3 – Typing Tightening
Updated Progress:
- ✅ `scheduler.*` and `api.*` under `disallow_untyped_defs`.
- ✅ Collectors strict & import-tightened: `defillama`, `txcount`, `hashrate`, `altme` (each with explicit TypedDict models & cache typing).
- ✅ WebSocket liquidation collector (`ws`) strict-typed with `LiquidationEntry` / `LiquidationMessage` schema and per-module `ignore_missing_imports = false`.
- ✅ Local stub for `diskcache` (minimal surface: Cache ctor/get/set) + documented in `typings/README.md`.
- ✅ Stub packages installed & verified via venv: `types-requests`, `types-PyYAML`, `pandas-stubs`.
- ✅ `warn_unused_configs = true` enabled (no spurious warnings).
- ✅ Per-module pilot of `ignore_missing_imports = false` for: collectors above + `api.*`.
- ✅ Removed stray unused type ignore in scheduler.
- ❌ (Deferred) `RUF100` adoption (postpone until legacy formatting churn reduced).
- ⏳ Next: Extend strict/import-tight set to remaining high-value collectors (e.g., WebSocket feeds) before considering global flip of `ignore_missing_imports`.

Refined Next Slice Candidates:
1. Add another network-facing collector (e.g., websocket module) to strict list; introduce typed message schema.
2. Evaluate remaining collectors for external libs lacking stubs; preemptively stub if low-risk.
3. Prototype enabling `disallow_incomplete_defs` in a single module to assess noise level.
4. Target small controlled subset for `RUF100` trial (exclude legacy exporters/reporters) to measure autofix ratio.

Revised Exit Criteria for Phase 3 (on track):
- ✅ Scheduler + API strict & import-clean.
- ✅ ≥4 collectors strict (current: 5 including websocket).
- ✅ Core external stub coverage (requests/httpx/yaml/pandas/diskcache) achieved.
- ✅ Documented stub policy (`typings/README.md`).
- ⏳ Decision point: readiness to widen `ignore_missing_imports = false` beyond pilot set.

Pilot Extensions:
- ✅ `disallow_incomplete_defs` enabled for `pipeline.collectors.hashrate` (noise level: zero) — candidate for broader rollout after 1–2 more modules trial.

### Phase 4 – Full Project Coverage
- Expand Ruff enforced scope to entire repository (drop non-blocking full scan step).
- Remove remaining per-file ignores; convert any persistent violations into targeted refactors or documented exceptions.

### Phase 5 – Optional Enhancements
- Adopt an auto-formatter (Black or Ruff formatter) for fully consistent style.
- Introduce performance-focused checks (e.g., `flake8-comprehensions` analog already mostly covered by Ruff SIM/PERF rules).
- Add pre-commit hooks running `ruff check --fix` and `mypy` on changed files only.

## Operational Guidelines
- New code: must be Ruff-clean and typed (no `Any` return types unless justified).
- Legacy refactors: when touching a legacy file, opportunistically apply Ruff auto-fixes and add/improve type hints.
- CI Policy: Non-blocking full-project Ruff scan stays until Phase 4 to provide visibility without friction.

## Tracking & Metrics
- Track count of Ruff violations in non-enforced scope weekly; target steady decline.
- Track mypy error count when expanding strictness; avoid >10% spike per phase.

## Rollback / Safety
- If enforcement expansion causes >5% test failure rate or >25% PR churn, revert scope change and slice smaller.

---
Maintained automatically; update when phases complete.

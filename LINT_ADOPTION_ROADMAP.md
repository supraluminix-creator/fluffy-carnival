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
Progress:
- ✅ Added mypy override: `disallow_untyped_defs = true` for `api.*` (in addition to existing `scheduler.*`).
- ✅ Added stub packages: `types-requests`, `types-PyYAML`, `pandas-stubs` already present.
- ✅ Removed an unused `# type: ignore` in `scheduler/runner.py` (keeps codebase tidy for future enabling of `warn_unused_ignores`).
- ✅ Pre-commit hook updated to include new stubs (ensuring local consistency).
- ❌ (Deferred) Enabling `RUF100` produced 146 issues (mostly tests / legacy scripts); postponed to a dedicated cleanup slice to avoid noisy diff.
- ⏳ To do: Introduce `warn_unused_configs = true` and then gradually dial down `ignore_missing_imports` after stubs coverage audit.
- ⏳ To do: Begin migrating selected collectors to stricter typing (pick 1–2 high-signal modules first).

Next Slice Candidates:
1. Add `warn_unused_configs = true` (low risk) — verify zero noise.
2. Audit imports causing implicit Any (sample collectors) and list required stubs or explicit Protocols.
3. Pilot `disallow_untyped_defs` on one collector module (e.g., `pipeline/collectors/defillama.py`).
4. Re-run experiment enabling `RUF100` limited to `pipeline/` (exclude tests) using per-file exclude to scope effort.

Exit Criteria for Phase 3:
- Scheduler + API strict (done)
- At least 1 collector strict with no unresolved mypy errors
- Stubs in place for common external libs (requests/httpx/yaml/pandas) — (done)
- Roadmap updated (this section)

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

## Follow-up: Expand lint scope to `pipeline` (Step 1)

Goal: Include `pipeline/` in Ruff only (keep Flake8/Mypy as-is) and add useful typing stubs for upcoming Mypy expansion.

### Scope

- CI Ruff command: change from
  - `python -m ruff check scheduler api`
  to
  - `python -m ruff check scheduler api pipeline`

- Do NOT change Flake8 or Mypy scopes in this PR.

### Cleanups

- Run `ruff --fix` locally and commit safe autofixes in `pipeline/`.
- Manually fix the top offenders surfaced by Ruff if small and safe.

### Typing stubs (prep for Step 3)

- Add stubs where helpful (no scope change yet):
  - `types-requests`
  - `pandas-stubs`
  - (Optional) `types-psutil`, `types-tabulate` if needed

Update `requirements.txt` accordingly under dev deps section.

### Tests

- `pytest -q` should stay green.
- Ruff (scoped to scheduler/api/pipeline) must pass.

### Checklist

- [ ] Updated CI Ruff scope to include `pipeline/` only
- [ ] Applied `ruff --fix` in `pipeline/`
- [ ] Added stub packages to `requirements.txt`
- [ ] Local run: `ruff`, `pytest` ✅
- [ ] Updated README (optional): note that Ruff now covers `pipeline/`

### Rollout plan

- Merge this PR when green. Next PR will move Flake8 to include `pipeline/` after fixing the top warnings flagged by Ruff.

# 📊 Analyse Technique Exhaustive — Crypto Monitor (Prod‑Safe)

Légende de statut: 
- Done — implémenté et correct
- Partial — présent mais incomplet / partiellement fiable
- Missing — absent dans le repo
- Not retained — volontairement non retenu (expliciter pourquoi)
- To improve — présent mais nécessite amélioration (expliquer quoi)
- To add — doit être ajouté (raison & priorité)

Date d’analyse: 18 septembre 2025

---

## 1) Parcours exhaustif du repo (extraits, preuves, statut, reco)

Remarque: chemins relatifs sous `new_crypto_prodsafe/`.

### A. Entrypoint & runtime

1. `main.py` — Entrée en mode scheduler sans API; configure logs, heartbeat, metrics opt., health HTTP
	- Preuves: lignes (setup_logging; heartbeat; ENABLE_METRICS; ENABLE_HEALTH; HealthHandler)
	- Statut: Done
	- Recommandation: To improve (High) — Ajouter un “boot banner” unique résumant run_id, config, ports, jobs; valider `scheduler/jobs.yaml` à chaud (clés inconnues, ids dupliqués).

2. `scheduler/runner.py` — Builder du scheduler APScheduler; wrapper des jobs avec métriques, persistance ok/err, readiness
	- Preuves: CRYPTO_TASK_*; CRYPTO_READY(_TS); set_build_info(); get_status_snapshot(); _STATE_FILE
	- Statut: Done
	- Recommandation: To improve (Medium) — Standardiser erreurs remontées par tasks (codes/causes), ajouter budgets par tâche (timeouts dédiés), et guardrails de concurrence par source.

3. `scheduler/jobs.yaml` — Config YAML des jobs avec substitution env
	- Preuves: ids macro/defillama/onchain_* etc.
	- Statut: Done
	- Recommandation: To improve (Medium) — Schéma YAML (pykwalify/cerberus/pydantic‑yaml) + check duplicate ids + lints CI.

### B. Collectors & orchestration

4. `pipeline/collectors/*` — Ensemble de fetchers (market, defillama, onchain, derivatives, sentiment, ws)
	- Preuves: fichiers présents; signatures async; usage httpx/requests; ws client
	- Statut: Partial — hétérogénéité sur timeouts/retry/cache/validation
	- Recommandation: To improve (High) — Unifier via un client HTTP commun (timeout, retry, backoff, headers), pydantic models pour réponses clés, validation ranges.

5. `pipeline/orchestrator.py` — Exécution parallèle des collectors legacy (batch)
	- Preuves: orchestrateur de ParallelOrchestrator
	- Statut: Partial — utile pour mode batch mais historique
	- Recommandation: Not retained (Low) — Préférer le scheduler YAML comme voie principale; garder l’orchestrateur pour batch spéciaux.

6. `pipeline/exporter.py` & export CSV dans `main.py`
	- Preuves: `EXPORT_FIELDS`, fichiers CSV sous `exports/`
	- Statut: Partial — pas de validation stricte de schéma
	- Recommandation: To add (High) — Pydantic `ExportRow` avec `schema_version`; tests golden; fail‑fast si champs manquants.

7. `pipeline/storage/*` — SQLite + migrations; parquet
	- Preuves: `sqlite_adapter.py`, `migrations.py`, parquet via pyarrow
	- Statut: Done
	- Recommandation: To improve (Low) — Ajout d’index ciblés; vacuum/pragma doc; health check DB dans /health.

### C. Observabilité & Ops

8. Logging structuré (structlog) + run_id + rotation fichiers
	- Preuves: `main.py::setup_logging()`; TimedRotatingFileHandler; per‑run file
	- Statut: Done
	- Recommandation: To improve (Low) — Boot banner + log “ready” (déjà ajouté) + sampler WARN si volumétrie.

9. Métriques Prometheus (optionnelles) + serveur /metrics
	- Preuves: ENABLE_METRICS; CRYPTO_TASK_*; CRYPTO_READY; CRYPTO_READY_TS; CRYPTO_BUILD_INFO; start_http_server
	- Statut: Done
	- Recommandation: To improve (Medium) — Docs des séries; histogram buckets adaptés par tâche; exemplars (future).

10. Health HTTP léger (/health, /ready, /live) + /metrics/ready texte
	 - Preuves: HealthHandler dans `main.py`; payload inclut ports/config; `scheduler.runner.get_status_snapshot()`
	 - Statut: Done
	 - Recommandation: To improve (Low) — Ajouter `started_uptime_s`, et un champ `version` top‑level.

11. Log summarizer (`tools/summarize_logs.py`)
	 - Preuves: CLI existant
	 - Statut: Done
	 - Recommandation: To improve (Low) — Flags pour filtres par job/task et export JSON ND.

### D. Tests & CI

12. `tests/` — Présents (collectors, ws, writer, integration basics)
	 - Preuves: `tests/test_ws_client.py`, `tests/test_writer.py`, `tests/test_integration.py`, etc.
	 - Statut: Partial — bonne base mais couverture inégale
	 - Recommandation: To improve (High) — Ajouter tests: config YAML validation, /health JSON shape, /metrics readiness, export schema guard, retry policy.

13. CI GitHub Actions `.github/workflows/ci.yml`
	 - Preuves: setup‑python 3.12; pip install; pytest -q
	 - Statut: Partial — pas de lint/format/security
	 - Recommandation: To add (High) — black/isort/ruff; safety or pip‑audit; pytest‑cov; artifacts pour logs sur échec.

### E. Documentation & scripts

14. `README.md`, `README_NEW_PRODSAFE.md` — Docs d’usage; Observability & Ops présent
	 - Preuves: sections ajoutées (env vars, endpoints)
	 - Statut: Done
	 - Recommandation: To improve (Low) — Ajouter un tableau “troubleshooting” Windows (ports occupés, perms, tee).

15. `scripts/run_scheduler.ps1` — Runner PowerShell
	 - Preuves: support ports, health toggle, version/git
	 - Statut: Done
	 - Recommandation: To improve (Low) — Param `-NoMetrics`; log file hint output.

---

## 2) Synthèse statuts

- Entrypoint/scheduler: Done (To improve: boot banner, YAML schema)
- Collectors: Partial (To improve: http client unified, pydantic validation)
- Exporter/schema: Partial (To add: schema guard + tests)
- Storage: Done (To improve: indexes, DB health)
- Observabilité: Done (To improve: buckets/doc)
- Tests/CI: Partial (To add: lint/security/coverage; health/metrics tests)
- Docs/scripts: Done (To improve: troubleshooting)

---

## 3) Recommandations priorisées (résumé)

1. Critical — Config banner + YAML validation + duplicate id check
2. High — Export schema (pydantic) + CI golden tests
3. High — Unified HTTP client with retry/backoff + per‑collector timeouts
4. High — CI linters + security scan + coverage gate
5. Medium — DB indexes + health DB step + uptime in /health
6. Medium — Metrics tuning (histogram buckets) + series doc

Chaque recommandation aura: action, fichiers touchés, tests, critères d’acceptation et rollback dans le plan d’améliorations.
<!-- markdownlint-disable -->

# 📜 CHANGELOG — new_crypto_prodsafe

## [0.1.3] - 2025-10-17
- Liquidations Bybit: service WebSocket `bybit_ws.py` enrichi (flush périodique, détection de flux idle, métriques d'écriture, ping configurables).
- Backfill historique: nouveau module `pipeline/collectors/bybit_backfill.py` + CLI `tools/bybit_liq_backfill.py` (cache local, déduplication, mode dry-run).
- Backfill auto: `tools/bybit_liq_auto_backfill.py` repère les jours manquants et enchaîne les téléchargements (option `--dry-run` pour simple audit).
- Audit archivage: ajout `tools/bybit_liq_gap_report.py` pour comparer DB, caches locaux et archives ZIP.
- Tests: `tests/test_bybit_backfill.py` couvre ingestion SQLite, déduplication et parse défensif.
- Documentation: playbook `docs/BYBIT_LIQUIDATIONS.md` détaillant collecte H24, backfill, gap report et intégration Task Scheduler.
- Migration: `BybitLiquidationsWriter` détecte l'ancien schéma (sans `qty_usd`) et le met à niveau automatiquement (recalcul + indexation) ; tests ajoutés.
- Outillage: `tools/bybit_liq_auto_backfill.py` automatise l'identification des jours manquants et déclenche le backfill en lots; nouveaux tests d'assistance (`tests/test_bybit_auto_backfill.py`).

## [0.1.2] - 2025-10-09
- VS Code: ajout des tâches "API: Run (detached on port)" et "API: Stop (PID)" pour un cycle start/stop plus ergonomique sous Windows.
- Smokes: documentation d’usage mise à jour dans `README_NEW_PRODSAFE.md` (AutoDetect + run détaché + arrêt par PID/port).
- Lint: passage rapide Ruff (auto-fix) et format; reste quelques avertissements mineurs non bloquants planifiés pour une passe ultérieure.

## [0.1.1] - 2025-10-08
- Bookmarklet: nouveaux drapeaux `/clear` (vider la zone avant injection) et `/unique` (ne pas ré‑injecter si contenu identique), JSDoc étoffé pour la maintenance.
- Bookmarklet: ajouts `/cursor:top|end` (position du caret) et `/btntext:"..."` (clic par libellé bouton).
- Bookmarklet: ajouts `/noform` (désactiver submit de formulaire) et `/maxlen:NNN` (troncature du prompt).
- Bookmarklet: filtres de sources `/noclip`, `/noselect`, `/novar`, `/noprompt` pour piloter l’ordre et l’usage des sources (clipboard, sélection, variable globale, prompt).
- Bookmarklet: utilitaires `/preview` (surlignage sans injection) et `/copy` (copier le texte transformé avant injection).
- Bookmarklet: drapeaux avancés `/debug` (traces console), `/clickguard:ms` (anti double‑clic), `/site:Nom` (forçage mapping), `/source:clip|select|var|prompt` (forcer la source).
 - Bookmarklet: presets et debug QOL: `/fastsend` (réduction délais/retries, clickguard réduit), `/logtext[:N]` (aperçu texte final en console).
- Scripts PowerShell: `run_uvicorn.ps1` (Windows‑friendly, auto‑port), `smoke_llm_api.ps1` (smoke HTTP), `smoke_llm_inprocess.ps1` (smoke in‑process), `build_bookmarklet.ps1` (génération rapide).
- VS Code: `.vscode/tasks.json` consolidé avec des helpers en 1‑clic (API run, smoke HTTP/in‑process, build bookmarklet).
 - Bookmarklet: alias et presets qualité‑de‑vie: `/enteronly`, `/clickonly`, `/slowsend`, `/noalert`, `/hl[:couleur]`, `/metaenter`, `/target:active|auto`, `/prewait:ms`.
 - Smoke: privilégier le smoke in‑process pendant le sprint; pour le HTTP, démarrer uvicorn dans un terminal dédié puis lancer `scripts/smoke_llm_api.ps1` depuis un autre.

## [0.1.0] - 2025-10-01
- Noyau prod-safe isolé (collecte/WS/ingestion/ETL) et outillage d’archivage (scan → exec → zip → rapports)
- Politique exemples: conserver ceux pertinents à la prod; archiver les générateurs non-core
- CI allégée et fiable (Ruff, Pytest, scans sécurité ciblés); scripts de smoke pour API/health
- Passe mypy légère (suppression d’ignore inutiles, annotations simples sur chemins critiques)
- Option export Parquet (pyarrow), lazy import et tests de latence/échec parquet
- Docs et scripts outils (secret_scan, benchmark collectors, prompts, logs summary)

## 2025-09-15
- Initialisation du projet, arborescence modulaire
- Migration du reporting PowerShell-friendly (reporter.py)
- Export CSV consolidé et horodaté (exporter.py)
- Création de tous les collectors manquants (SOPR, Bybit WS, Defillama, etc.)
- Intégration et validation par tests unitaires
- Ajout CI/CD GitHub Actions
- Documentation complète générée

## 2025-09-16
- Ajout tests unitaires pour chaque collector
- Correction des imports PYTHONPATH pour compatibilité workspace multi-projets
- Optimisation du main.py pour validation rapide de chaque module

## 2025-09-17
- Génération du diagramme technique (architecture, modules, flux)
- Analyse approfondie du code, dépendances, points d’optimisation
- Requirements.txt adapté et validé

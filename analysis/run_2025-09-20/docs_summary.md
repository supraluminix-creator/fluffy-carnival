# Synthèse Documentation (run 2025-09-20)

## Méthode
Lecture ciblée des principaux fichiers Markdown listés par `git ls-files *.md`. Extraction pour chacun : intention, attentes clés (timings, fallback, qualité), écarts/contradictions potentielles.

---
## 1. README.md
Intention: Présentation opérationnelle du pipeline new_crypto_prodsafe (exécution scheduler, observabilité, couverture, roadmap de tests). Met l'accent sur usage Windows/PowerShell, variables d'environnement, endpoints metrics/health, stratégie de montée en couverture.
Attentes clés:
- Execution via scheduler + jobs YAML.
- Export CSV (latest + horodaté).
- Observabilité: metrics Prometheus + health server.
- Couverture > paliers (objectif progressif 80%+).
- Documentation des exclusions couverture.
Écarts/Notes: README ne reflète pas entièrement la stratégie circuit breaker récente ni l'adaptation fail-under à 94% (ajout fait lors des derniers commits). Mention partielle de Parquet (ajout dans nouvelle section récente ok).

## 2. DIAGRAMME_ARCHITECTURE.md
Intention: Vue mermaid simplifiée du flux main -> reporter/exporter/collectors/storage/tests.
Attentes clés:
- main orchestre exporters, collectors, stockage, production d'exports.
- Présence de modules SQLite adapter/migrations (certains non présents ou renommés dans l'arborescence actuelle: vérifier storage/ vs pipeline/storage/ existants).
Écarts/Notes: Diagramme inclut des collectors (sopr_bgeometrics.py, sopr_blockchain.py) pas visibles dans l'arborescence actuelle (à confirmer). bybit_ws montré mais aujourd'hui traité via liquidations writer séparé. Tests indiqués (test_collectors.py, test_signals.py, test_exporter.py) tandis que la suite réelle est plus granulaire.

## 3. CHANGELOG.md
Intention: Historique journalier initialisation et ajouts (15-17 sept). Focus sur mise en place structure, tests, CI, diagramme.
Attentes clés:
- Cohérence entre dates et commits (à valider via log git si besoin).
- Décrit création collectors manquants.
Écarts: Ne couvre pas les développements récents (circuit breaker, métriques cache, partitionnement Parquet). Mise à jour requise pour refléter sprint couverture.

## 4. COPILOT_COLLECTORS_OPTIMISATION.md
Intention: Source de vérité des timings, rôles Main/Backup, quotas, architecture collectors.
Attentes clés:
- Respect timings 300s/900-1800s/3600s/6h et flux temps réel pour Bybit WS.
- Implémentation fallback Main→Backup pour chaque domaine (prix, macro, dérivés, on-chain, deFi, sentiment).
- Intégration caches, retry/backoff, logs, tests.
Écarts: Tous les collectors ne semblent pas encore unifiés sous un base_collector abstrait; certains fallbacks partiels (ex: market partiel CoinGecko→CMC présent; derivatives Bybit→Binance partiellement implémenté pour OI, L/S ratio sans fallback secondaire). WebSocket Bybit consolidé séparé mais statut test à vérifier.

## 5. PROMPT_START_PROD_SAFE.md
Intention: Sprint 1 priorités (fallback généralisé, retry central, scheduler granulaire, structlog, Prometheus, base_collector) avec méthodologie ANALYSE → SOLUTION → DELTA.
Attentes clés:
- Création base_collector.
- Refactor collectors pour héritage commun.
- Scheduler 5/15/30/60/6h.
- Retry/backoff décorateur central.
Écarts: base_collector absent / non trouvé (à confirmer). Retry/backoff géré localement (tenacity décorateur direct dans certains collectors) non centralisé. Scheduler granulaire partiellement (fichier jobs.yaml mentionné vs réel?).

## 6. PROMPT_COPILOT_NEW_PRODSAFE.md
Intention: Reboot du monolith vers architecture modulaire dans new_crypto_prodsafe avec étapes d'analyse, extraction, refactor, extensions (SOPR modules, WS, export).
Attentes clés:
- Présence analysis/monolith-comparison.md.
- Modules sopr_bgeometrics / sopr_blockchain / bybit_ws.
- Export CSV + reporting PowerShell ré-implémentés.
Écarts: monolith-comparison.md manquant. Modules sopr_* à vérifier (non vus dans listing courant). bybit_ws existe sous collectors? (à rechercher). Export et reporter présents.

## 7. PROMPT_BYBIT_WS_PRODSAFE.md
Intention: Intégration robuste Bybit WebSocket (reconnect, backoff, métriques, tests, process indépendant).
Attentes clés:
- Module bybit_ws.py avec auto-reconnect, métriques Prometheus, tests mocks WS.
- Flush tampon (5s ou 100 events) vers DB / export.
Écarts: Actuel writer liquidations partition Parquet (batch flush) présent; nécessité de confirmer composant WS temps réel + tests simulés.

## 8. LINT_ADOPTION_ROADMAP.md
Intention: Plan d’adoption progressive Ruff + mypy strict par phases.
Attentes clés:
- CI exécutant Ruff + mypy sur périmètre prioritaire.
- Extensions futures (RUF100, ignore_missing_imports flip) documentées.
Écarts: CI actuelle inclut lint + mypy + bandit (conforme); vérifier périmètre strict vs roadmap (pas entièrement strict encore, conforme au plan). Mise à jour récente partielle.

## 9. Sourcing - Timing APIs & Collectors.md
Intention: Tableau pragmatique récap timings consolidé (double de COPILOT_COLLECTORS_OPTIMISATION mais format différent) + hiérarchie Main/Backup.
Attentes clés:
- Alignement scheduler sur ces cadences.
- Collectors distinguant clearly Main vs Backup.
Écarts: Non prouvé dans code côté scheduler (à auditer dans phase exécution). Répétition d'info (cohérente mais maintenance double).

---
## Contradictions / Gaps transverses
- base_collector exigé mais introuvable.
- monolith-comparison.md manquant.
- Timings granulaire scheduler non encore vérifiés (documentation vs implémentation).
- CHANGELOG pas à jour sur ajouts récents (breaker, metrics caches, partition parquet).
- WebSocket Bybit : doc attend service H24 robuste; existence et tests à confirmer.
- Fallback complet multi-domaines pas uniformisé (certains collectors partiels).

---
## Pistes de validation lors des runs
1. Vérifier existence & usage scheduler jobs YAML + correspondance timings.
2. Inspecter presence bybit_ws et flux réel (ou fallback mode test).
3. Vérifier fallback dans market (CoinGecko→CMC) et derivatives (Bybit→Binance) effectifs via logs.
4. Lister collectors manquants par rapport au tableau (sentiment, on-chain multiples). 

---
## Prochaines étapes (avant phase d'exécution)
- Confirmer arborescence collectors manquants.
- Préparer scripts d'exécution one-shot pour limiter consommation API.
- Mettre à jour CHANGELOG après audit.



# new_crypto_prodsafe — Pipeline Crypto Production-Grade

## Sommaire
- [Contexte](#contexte)
- [Architecture](#architecture)
- [Modules principaux](#modules-principaux)
- [Collectors](#collectors)
- [Reporting & Export](#reporting--export)
- [Tests & CI/CD](#tests--cicd)
- [Utilisation rapide](#utilisation-rapide)
- [Diagramme comparatif](#diagramme-comparatif)

---

## Contexte
Refactoring complet du MONOLITH (V1→V3) pour un pipeline crypto modulaire, robuste, et prêt pour la prod. Méthodologie prod-safe, reporting PowerShell, export CSV horodaté, collectors multi-API, fallback, et tests automatisés.

## Architecture
```
new_crypto_prodsafe/
├── main.py
├── pipeline/
│   ├── collectors/  # Tous les modules de collecte (SOPR, Bybit, Defillama...)
│   ├── reporter.py  # Reporting PowerShell-friendly
│   ├── exporter.py  # Export CSV consolidé
│   └── ...
├── exports/
├── data/
├── tests/
└── .github/workflows/ci.yml
```

## Modules principaux
- `main.py` : Entrée du pipeline, intégration de tous les collectors
- `pipeline/collectors/` : Collecteurs spécialisés (SOPR, Bybit WS, Defillama, etc.)
- `pipeline/reporter.py` : Affichage lisible, tabulate/pandas
- `pipeline/exporter.py` : Export CSV unique + horodaté

## Collectors
- `sopr_bgeometrics.py` : SOPR via BGeometrics
- `sopr_blockchain.py` : SOPR on-chain
- `bybit_ws.py` : WebSocket Bybit robuste (reconnect/backoff)
- `defillama.py` : TVL, yield
- `txcount.py` : Nombre de transactions on-chain
- `hashrate.py` : Hashrate on-chain
- `altme.py` : KYC/identity Altme

## Reporting & Export
- Interface PowerShell-friendly, tabulate ou pandas
- Export CSV consolidé dans `exports/`, version horodatée

## Tests & CI/CD
- Pytest pour tous les modules (collectors, reporter, exporter)
- Workflow GitHub Actions minimal (`.github/workflows/ci.yml`) : Ruff + Pytest à chaque push/PR
- Commande locale : `pytest -v`

## Utilisation rapide
```bash
# Installation
pip install -r requirements.txt

# Lancer le pipeline principal
python main.py

# Lancer les tests
pytest -v
```

### Analyse de marché multi-actifs (LLM)

Un utilitaire CLI compose un prompt à partir des exports locaux (`exports/export_manifest.jsonl`, CSV d’indicateurs) et de la base SQLite (liquidations Bybit si présente), puis appelle un LLM configurable via variables d’environnement pour produire un rapport Markdown.

Prérequis (au choix selon provider) dans `.env.local`:

```
# Anthropic (Claude)
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-3-haiku-20240307

# OpenRouter
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openrouter/auto

# OpenAI
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini

# Gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-1.5-flash

# Deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-chat

# Optionnel (ETH txcount fallback)
ETHERSCAN_API_KEY=...
```

Exécution:

```
python tools/market_analysis_prompt.py --assets "BTC,ETH,SOL,LINK,TAO,RNDR,ATOM,DOT,NEAR,AVAX,SUI" --hours 24 --enrich-api
```

Options:
- `--provider`: forcer le provider (`anthropic|openrouter|openai|gemini|deepseek|ollama|mock`).
- `--dry-run`: n’appelle pas le LLM, génère uniquement le prompt et le rapport.

Sortie: `exports/analysis/market_analysis_YYYYMMDD_HHMMSS_UTC.md`.

### API LLM — tâches VS Code (Windows)

Pour démarrer/arrêter l’API localement de façon fiable pendant les smokes:

- Démarrer en détaché (choix du port): tâche "API: Run (detached on port)" → saisir le port (ex: 8000). La tâche affiche le PID.
- Vérifier rapidement: tâche "Smoke: HTTP (AutoDetect)" → détecte l’API (8000..8105) et vérifie `/api/llm/status`.
- Arrêter l’API:
  - Par PID: tâche "API: Stop (PID)" → collez le PID affiché au démarrage.
  - Ou par port: tâche "API: Stop (port)" → saisissez le port (ex: 8000).

Notes:
- Ces tâches utilisent PowerShell (Windows) et les scripts du dossier `scripts/`.
- Pendant le sprint, privilégier les smokes (in‑process/HTTP) et réserver Pytest pour la fin.

### Endpoints de base (API LLM)

- GET `/` et GET `/api` — pages d’accueil (ping rapide).
- GET `/api/health` et alias GET `/health` — santé JSON légère.
- GET `/api/version` et alias GET `/version` — métadonnées de build/version.

Astuce:
- Tâche VS Code: "Smoke: Basic API" — vérifie `/`, `/api`, `/api/health`, `/api/version`, `/health`, `/version` avec autodétection de port.

## Observabilité & Ops

Le scheduler expose des logs structurés, des métriques Prometheus optionnelles et un mini serveur HTTP de santé.

### Variables d'environnement

- ENABLE_SCHEDULER=1 — Active le scheduler YAML (défaut 1)
- SCHEDULER_CONFIG=scheduler/jobs.yaml — Chemin du fichier YAML des jobs
- RUN_JOBS_AT_START=1 — Exécute les jobs immédiatement au démarrage (défaut 1)
- HEARTBEAT_SECS=60 — Intervalle du heartbeat en secondes
- RUN_ID — Identifiant de corrélation ajouté aux logs/CSV/métriques
- ENABLE_METRICS=1 — Démarre le serveur de métriques Prometheus
- METRICS_PORT=9300 — Port des métriques
- ENABLE_HEALTH=1 — Démarre le petit serveur HTTP de santé (défaut 1)
- HEALTH_PORT=9310 — Port du serveur santé
- APP_VERSION — Version applicative (exportée en métriques)
- GIT_SHA — SHA git (exporté en métriques)
- ENABLE_WHALE_BALANCES=1 — Active le collector Etherscan (legacy + scheduler)
- ETHERSCAN_ENABLED=1 — Active la configuration Etherscan (clés et listes d'adresses)
- ETHERSCAN_API_KEY=... — Clé Etherscan requise pour les appels `balancemulti`
- ETHERSCAN_ADDRESSES=0xAAA,0xBBB — Liste d'adresses (séparateur virgule / retour-ligne)
- ETHERSCAN_THRESHOLD_ETH=10 — Seuil pour les transactions "whale" (événements)

### Endpoints

- Prometheus: http://localhost:9300/metrics
  - Exemples:
    - crypto_ready — 1 après la première tâche OK
    - crypto_ready_timestamp — timestamp Unix de readiness
    - crypto_build_info — info build (Info metric ou Gauge avec labels)
    - crypto_task_* — compteurs et durées par tâche

- Santé JSON (léger): http://localhost:9310/health
  - Alias: /ready, /live
  - Inclut: run_id, jobs, started_at, ready, ready_ts, tasks (ok/err), build {version, git_sha, run_id}, ports {metrics, health}, config_path

- Texte minimal (sans Prometheus): http://localhost:9310/metrics/ready
  - Corps:
    ready 1
    ready_timestamp 1726640000

### Données whales ETH

- Collecteur activable via `ENABLE_WHALE_BALANCES=1` + configuration `ETHERSCAN_*`.
- Export JSON: `exports/onchain/etherscan_whale_balances.json` (adressage + total ETH).
- API REST: `GET /api/whales/balances` → liste des adresses, total agrégé, timestamp.
- Script CLI: `python -m scripts.dump_whale_balances` (rafraîchit, puis affiche un tableau ou JSON).
- Métriques Prometheus: `whale_balance_total_eth`, `whale_balance_address_eth`, `whale_balance_snapshot_timestamp`.

### Données insider whales (Hyperliquid + ETH)

- Activer via `ENABLE_WHALE_INSIDER=1` + configuration `HYPERLIQUID_*` (et `ETHERSCAN_*` pour compléter les soldes on-chain).
- Export JSON: `exports/whales/whale_insider_snapshot.json` (positions Hyperliquid normalisées + métrique agrégée Etherscan).
- API REST: `GET /api/whales/insider` → snapshot combiné (`records`, compteurs de surveillance, détails traders dérivés).
- Script CLI: `python -m scripts.dump_whale_insider` (rafraîchit ou charge le snapshot et affiche un résumé des positions surveillées).
- Métriques Prometheus: `whale_hyperliquid_position_notional_usd`, `whale_hyperliquid_position_leverage`, `whale_hyperliquid_last_updated_timestamp`.

### Lancer (PowerShell)

```
./scripts/run_scheduler.ps1 -MetricsPort 9300 -HealthPort 9310 -RunJobsAtStart -HeartbeatSecs 60 -RunId RUN123 -AppVersion 1.2.3 -GitSha abcdef0
```

Vérifier:

```
curl.exe http://localhost:9300/metrics
Invoke-RestMethod http://localhost:9310/health | ConvertTo-Json -Depth 4
curl.exe http://localhost:9310/metrics/ready
```

## Diagramme comparatif
```
MONOLITH V3   →   v15.2   →   new_crypto_prodsafe
[Legacy, monolithique]   [multi-API, CSV, reporting]   [modulaire, prod-safe, CI/CD]
```

---

## Journal de version
Voir `CHANGELOG.md` pour le suivi des évolutions.
│   │   ├── hashrate.py
│   │   ├── txcount.py
│   │   └── altme.py
│   └── storage/
│       ├── sqlite_adapter.py
│       └── migrations.py
├── main.py
└── tests/
    ├── test_collectors.py
    ├── test_signals.py
    └── test_exporter.py
```

---

## 🚀 Fonctionnalités principales
- **Collecte multi-sources** (marché, on-chain, dérivés, sentiment, macro).  
- **Fallbacks robustes** : valeurs par défaut si API en échec.  
- **Reporting PowerShell-friendly** (via tabulate ou pandas).  
- **Exports CSV consolidés** :  
  - `latest_export.csv`  
  - `pipeline_export_<timestamp>.csv`  
- **Métriques avancées** :  
  - SOPR (BGeometrics / SOPR_blockchain).  
  - Bybit WebSocket (liquidations, OI).  

---

## 🔒 Méthodologie prod-safe
Chaque modification suit le cycle :  
1. **ANALYSE** → compréhension et audit.  
2. **SOLUTION PROD-SAFE** → code complet, testé, prêt pour prod.  
3. **DELTA EXPLICATIF** → commit clair, diff minimal.  

---

## 🧪 Tests & CI/CD
- **Tests unitaires** avec Pytest.  
- **CI/CD GitHub Actions** :  
  - Installe dépendances.  
  - Lance `pytest -q`.  
- **Smoke tests manuels** : exécution `python main.py` pour vérifier reporting + exports.  

---

## 🧹 Lint scope strategy (CI stricte mais verte)

Pour garder une CI stricte sans être bloquée par la dette historique, la vérification de style/typage est limitée d'abord à des dossiers ciblés, puis élargie progressivement.

- Portée actuelle (CI): `scheduler/` et `api/`
  - Ruff: `python -m ruff check scheduler api`
  - Flake8: `python -m flake8 scheduler api`
  - Mypy: `python -m mypy scheduler api`

- Plan d'élargissement (petites PRs, ciblées):
  1) Ajouter `pipeline/` à Ruff (autocorrections rapides)
    - `python -m ruff check scheduler api pipeline`
  2) Ajouter `pipeline/` à Flake8 après correction des principaux avertissements
    - `python -m flake8 scheduler api pipeline`
  3) Ajouter `pipeline/` à Mypy une fois les trous de types comblés
    - Ajouter des stubs si besoin (ex: `types-requests`, `pandas-stubs`)
    - `python -m mypy scheduler api pipeline`

Conseils:
- Élargir par sous-dossiers si nécessaire (ex: `pipeline/collectors` d'abord).
- Garder les PRs petites et atomiques (1 règle/zone corrigée à la fois).
- Exécuter localement avant push pour éviter des surprises en CI.

---

## 📈 Roadmap
- [ ] Phase 1 : Analyse des MONOLITH V1–V3.  
- [ ] Phase 2 : Extraction du meilleur code.  
- [ ] Phase 3 : Refactorisation en pipeline modulaire.  
- [ ] Phase 4 : Extensions (SOPR, Bybit WS).  
- [ ] Phase 5 : CI/CD complet et documentation enrichie.  

---

## 📊 Diagramme de filiation
```
MONOLITH (V1 → V3) 
        │
        ▼
 crypto_pipeline_v15_2 (recodé, CSV + SOPR)
        │
        ▼
 new_crypto_prodsafe (refactorisé prod-grade, + SOPR/WS)
```

---

## 📜 Licence
Projet privé — usage interne.


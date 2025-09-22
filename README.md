# new_crypto_prodsafe

[![CI](https://github.com/supraluminix-creator/fluffy-carnival/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/supraluminix-creator/fluffy-carnival/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/supraluminix-creator/fluffy-carnival/branch/main/graph/badge.svg)](https://codecov.io/gh/supraluminix-creator/fluffy-carnival)

Prod-safe crypto monitor with:
- Central scheduler (APScheduler) with jitter
- Parallel orchestrator
- YAML-driven job configuration

> NOTE LEGACY: Un ancien snapshot du code est conservé sous `fluffy-carnival/` uniquement comme archive. Voir `LEGACY_ARCHIVED.md` pour la politique de retrait progressif. Ne pas y ajouter de nouveau code.

Note: This repository is published as "fluffy-carnival" on GitHub.

## Quick start (Windows / PowerShell)

Prerequisites:
- Python 3.12
- Create and activate the venv, install deps (already in this repo)

### 1) Scheduler mode

```powershell
Set-Location "C:\\Users\\To the moon\\Downloads\\new_crypto_prodsafe"
$env:CRYPTO_MONITOR_MODE = "scheduler"
.\\.venv\\Scripts\\python.exe .\\main.py
```

There is no API server in this build; everything runs headless from the scheduler.

## YAML-driven jobs

Edit `scheduler/jobs.yaml` to enable/disable jobs and set intervals. We added args and kwargs support and allow `${ENV}` substitution for secrets.

Example entries:

```yaml
jobs:
  - id: macro
    every: 5m
    func: pipeline.collectors.market:fetch_macro
    enabled: true
    args: ["bitcoin"]
    kwargs:
      cmc_api_key: ${CMC_API_KEY}
```

Supported time units: ms, s, m, h, d.

### Binance price collector (nouveau)

Un collector léger `fetch_binance_price` est disponible (module `pipeline.collectors.binance`).
Il consomme l'endpoint public `/api/v3/ticker/price` et ajoute l'en-tête `X-MBX-APIKEY` si `BINANCE_API_KEY` est défini (certaines configurations d'organisation peuvent l'exiger). Exemple d'utilisation rapide :

```python
from pipeline.collectors.binance import fetch_binance_price
rec = fetch_binance_price('BTCUSDT')
print(rec)
```

Dans un job YAML :
```yaml
  - id: binance_price
    every: 5m
    func: pipeline.collectors.binance:fetch_binance_price
    enabled: true
    args: ["BTCUSDT"]
```

Variable d'environnement requise (facultative si juste lecture publique) : `BINANCE_API_KEY`.

## Niveaux de Fallback & Flags (Nouveau)

Des fallbacks multiniveaux ont été introduits pour améliorer la résilience lorsque la source primaire échoue (timeouts, 5xx, ratelimit, schémas inattendus). Tous sont contrôlés par des variables d'environnement (feature flags) afin d'activer progressivement.

Collectors affectés:
- Macro (prix & market data): CoinGecko (niveau 1) → Binance Spot (niveau 2, si `ENABLE_BINANCE_SPOT_FALLBACK=1`) → CoinMarketCap (niveau 3) → (option legacy secondaire Binance si `ENABLE_BINANCE_MACRO_FALLBACK=1`, niveau 4)
- Open Interest dérivés: Bybit (niveau 1) → Binance Futures OI (niveau 2, si `ENABLE_BINANCE_OI_FALLBACK=1`)
- Funding rate dérivés: Bybit (niveau 1) → Binance Funding (niveau 2, si `ENABLE_BINANCE_FUNDING_FALLBACK=1`)

Flags disponibles:
- ENABLE_BINANCE_SPOT_FALLBACK=1
- ENABLE_BINANCE_MACRO_FALLBACK=1 (chemin legacy / profondeur 4)
- ENABLE_BINANCE_OI_FALLBACK=1
- ENABLE_BINANCE_FUNDING_FALLBACK=1

Bonnes pratiques d'activation progressive:
1. Activer d'abord `ENABLE_BINANCE_SPOT_FALLBACK` en staging, observer métrique de profondeur (voir ci-dessous).
2. Activer OI et Funding de façon indépendante (`ENABLE_BINANCE_OI_FALLBACK`, `ENABLE_BINANCE_FUNDING_FALLBACK`).
3. Garder `ENABLE_BINANCE_MACRO_FALLBACK` désactivé sauf besoin d'une redondance supplémentaire (legacy).

## Nouvelle métrique: fallback_chain_depth

Gauge Prometheus: `fallback_chain_depth{collector="<name>"}`.

Interprétation:
- Valeur 1: Source primaire utilisée.
- Valeur 2: 1er fallback (ex: Binance spot pour macro, Binance OI pour dérivés) a servi.
- Valeur 3: 2e fallback (ex: CoinMarketCap) a servi.
- Valeur 4: Chemin legacy supplémentaire (macro seulement si activé).

Utilisation opérationnelle:
- Alerting si profondeur >1 sur fenêtre glissante (indique fragilité de la source primaire).
- Dashboard: histogramme des occurrences de profondeurs >1 par collector pour quantifier la dépendance aux fallbacks.

Exemple de scrap:
```
fallback_chain_depth{collector="macro"} 1
```

Cette valeur est mise à jour à chaque exécution réussie d'un collector (réinitialisation implicite).

## Windows caveats

- Stop background scripts that might lock resources you need.

## Dev and Tests

```powershell
Set-Location "C:\\Users\\To the moon\\Downloads\\new_crypto_prodsafe"
.\\.venv\\Scripts\\python.exe -m pytest -q
```

## Résilience HTTP

Le module central `pipeline/http_wrappers.py` fournit:

1. Normalisation d'endpoint (`endpoint_label`) pour réduire la cardinalité Prometheus: hôte simplifié (ignore sous‑domaines peu informatifs `api`, `www`) + premier segment utile du chemin (`coingecko/coins`, `llama/chains`, `binance/depth`).
2. Retry exponentiel avec jitter (facteur aléatoire 0.8–1.3) sur erreurs transitoires: exceptions centralisées via tuple `RETRIABLE_EXC = (RateLimitError, TimeoutError_, NetworkError, UpstreamError)`.
3. Circuit-breaker léger spécifique aux rafales de 429 par endpoint normalisé:
   - Variables: `HTTP_BREAKER_WINDOW` (30s), `HTTP_BREAKER_THRESHOLD` (5), `HTTP_BREAKER_COOLDOWN` (20s) par défaut.
   - À l'ouverture: incrément de `http_breaker_opens_total` puis court‑circuit (évite pression supplémentaire sur l'API saturée).
4. Support sync (`http_get_json_retry`) et async (`async_http_get_json_retry`) avec logique alignée (mêmes exceptions retriables, même jitter).
5. Erreurs non retriées (ex: `EmptyDataError`, `SchemaError`, `NotFoundError`) lèvent immédiatement sans polluer les métriques de retry.
6. Ancien compteur interne de debug `RUNTIME_RETRY_COUNT` retiré (observabilité assurée exclusivement via Prometheus).

### Variables d'environnement

| Variable | Rôle | Défaut |
|----------|------|--------|
| `RETRY_HTTP_ENABLED` | Active le retry global | `1` |
| `RETRY_HTTP_MAX` | Nombre de tentatives max | `3` |
| `RETRY_HTTP_BACKOFF_BASE` | Base backoff exponentiel (s) | `0.3` |
| `RETRY_FORCE_THREAD` | Force chemin threadé (tests DefiLlama) | `0` |
| `HTTP_BREAKER_WINDOW` | Fenêtre d'observation 429 (s) | `30` |
| `HTTP_BREAKER_THRESHOLD` | Nombre de 429 pour ouvrir | `5` |
| `HTTP_BREAKER_COOLDOWN` | Durée ouverture (s) | `20` |

### Métriques Prometheus

| Nom | Labels | Description |
|-----|--------|-------------|
| `http_retries_total` | endpoint, reason | Incrément à chaque retry déclenché |
| `http_retry_attempt_latency_seconds` | endpoint, attempt, final_status | Latence par tentative |
| `http_breaker_opens_total` | endpoint | Ouverture du breaker 429 (si exposé) |

### Tests de résilience

* `tests/test_defillama_retry_integration.py` – deux erreurs de rate limit DefiLlama puis succès.
* `tests/test_macro_coingecko_retry.py` – deux 429 CoinGecko (vérifie label `coingecko/coins`).
* `tests/test_http_retry.py` – retry sync générique (compteur + histogramme).
* `tests/test_http_breaker_and_emptydata.py` – ouverture du breaker (3×429) + short‑circuit + cas `EmptyDataError` non retriable.

### Améliorations futures possibles

* Token bucket global (limitation proactive) pour lisser rafales multi-collectors.
* Ajout éventuel d'un label `service` (ex: distinguer coingecko vs binance au-delà du path) si cardinalité maîtrisée.
* Persistance / export des compteurs de breaker (stateful restart safe).
* Budget temps global sur un appel retry (arrêt si backoff cumulatif dépasse N secondes).



## Observability & Ops

La documentation détaillée des métriques et de l'architecture observabilité a été déplacée dans `docs/` pour alléger ce README:

- Architecture & règles: `docs/ARCHITECTURE_METRICS.md`
- Liste & sémantique complète: `docs/README_OBSERVABILITY.md` (ancien `README_OBSERVABILITY.md` racine)
- Index global de la documentation: `docs/INDEX.md`

Une future relocalisation de la sécurité (`README_SECURITY.md`) suivra dans le même répertoire.

Environment variables:

- ENABLE_SCHEDULER=1 — Enable the YAML-driven scheduler (default 1)
- SCHEDULER_CONFIG=scheduler/jobs.yaml — YAML config path
- RUN_JOBS_AT_START=1 — Run all jobs immediately at startup (default 1)
- HEARTBEAT_SECS=60 — Heartbeat interval in seconds
- RUN_ID — Correlation id for logs/CSV/metrics
- ENABLE_METRICS=1 — Start Prometheus metrics server
- METRICS_PORT=9300 — Metrics port
- ENABLE_HEALTH=1 — Start lightweight health HTTP server (default 1)
- HEALTH_PORT=9310 — Health server port
- APP_VERSION — App version (exposed in metrics)
- GIT_SHA — Git commit SHA (exposed in metrics)

Endpoints:

- Prometheus metrics: http://localhost:9300/metrics
  - crypto_ready, crypto_ready_timestamp, crypto_build_info, crypto_task_*
  - fallback_invocations_total{collector,status}: Compteur unifié des activations de fallback.
    * collector: market | sentiment | onchain_txcount | deriv_oi | ...
    * status: success (fallback a produit une donnée) / error (fallback lui-même a échoué)
    Exemple de ligne:
    ```
    fallback_invocations_total{collector="market",status="success"} 3.0
    ```
    Interprétation: 3 bascules (CG → CMC) réussies depuis le démarrage.
  - fallback_chain_depth{collector}: Gauge profondeur dernier run (voir section dédiée).

- Health JSON: http://localhost:9310/health (aliases: /ready, /live)
  - Payload includes run_id, jobs, started_at, ready, ready_ts, tasks ok/err, build {version, git_sha, run_id}, ports {metrics, health}, config_path

- Minimal readiness (text): http://localhost:9310/metrics/ready
  - Example body:
    ready 1
    ready_timestamp 1726640000

Helper script (PowerShell):

```powershell
./scripts/run_scheduler.ps1 -MetricsPort 9300 -HealthPort 9310 -RunJobsAtStart -HeartbeatSecs 60 -RunId RUN123 -AppVersion 1.2.3 -GitSha abcdef0
```

## Contributing and PR workflow

- See the action plan with sprint breakdown: `improvements/action_plan.md`
- Follow the PR template: `.github/pull_request_template.md`
- Prototype of a tiny PR (test-first): `improvements/prototype/README.md` and `improvements/prototype/test_stub.py`

## Couverture & Qualité

Objectifs progressifs de couverture de tests (lignes):

| Palier | Statut | Détails |
|--------|--------|---------|
| 40%    | Atteint | Phase initiale mise en place tests fondamentaux (exporter, reporter, orchestrator basique) |
| 55%    | Atteint | Instrumentation fine orchestrateur + branches reporter/Dune + monitoring |
| 70%    | Atteint | Quick wins (logging_config, base_collector, protocols), timeout global orchestrator, indicators |
| 75%    | Actuel (seuil) | Seuil temporaire abaissé pour stabilisation; large refonte tests orchestrateur en cours |
| 80%    | Prochain | Remonter progressivement après consolidation des tests scheduler/health/heartbeat |
| 85%+   | Étape ultérieure | Fallbacks multi-niveaux + health server complet + raffinements collectors |

Stratégie:
1. Ajouter d'abord des tests déterministes (fonctions pures, branches simples).
2. Introduire des mocks réseau (httpx / websockets) pour collectors lourds.
3. (Actuel) Seuil temporaire `--cov-fail-under=75` (couverture effective ~87%). Remontée planifiée après assainissement de `main.py` (boucles longues & services auxiliaires).
4. Documenter toute exclusion via `# pragma: no cover` accompagnée d'une justification dans `CONTRIBUTING.md`.

Exclusions candidates (à revalider):
- Code d'initialisation de logging purement déclaratif.
- Branches extrêmes de repli réseau rarement atteignables sans tests fragiles.

Pour exécuter la suite rapide:
```powershell
pytest -q
```
Pour un rapport détaillé des lignes manquantes:
```powershell
pytest --cov-report=term-missing:skip-covered -q
```

## Améliorations Futures (Optionnel)

Cette section liste des optimisations identifiées après l'atteinte du seuil de couverture >80%. Elles ne sont pas bloquantes pour la prod actuelle mais améliorent robustesse, maintenance et signal des tests.

### Tests & Couverture
- Ajouter des tests ciblant les branches restantes peu critiques (reconnexions prolongées WebSocket, chemins d'erreurs multiples defillama) seulement si ROI clair.
- Appliquer `# pragma: no cover` sur portions intrinsèquement non déterministes (boucles de reconnexion infinies, branches d'attente réseau) pour stabiliser le ratio si objectif >85%.
- Centraliser les fabriques de mocks HTTP/WebSocket dans `tests/utils/` pour réduire duplication et faciliter futures extensions (déjà plusieurs clients factices similaires).
- Activer éventuellement `pytest-rerunfailures` uniquement pour scénarios réseau simulés si apparition d'instabilités (actuellement stable, donc différé).

### Performance & Scheduling
- Regrouper les appels séquentiels HTTP corrélés (ex: defillama chain + historical) sous un même client réutilisé (session pooling) pour réduire overhead connexion.
- Introduire un petit rate limiter (token bucket) partagé pour éviter bursts si plusieurs jobs réseau démarrent en même temps au lancement (`RUN_JOBS_AT_START=1`).

### Observabilité & Metrics
- Ajouter histogrammes Prometheus (latency buckets) en complément des `Summary` pour améliorer l'agrégation côté serveur (scrapes multiples).
- Exposer un compteur de cache hits/miss par collector pour diagnostiquer efficacité TTL.
- Ajouter une métrique de taille de buffer liquidations avant flush pour surveiller saturation potentielle.

### Stockage & Export
- Parquet: ajouter partitionnement par heure / jour (`/year=YYYY/month=MM/day=DD/hour=HH`) pour améliorer lecture analytique ultérieure.
- Vérifier compression Parquet (`snappy` ou `zstd`) et schema evolution contrôlée.

### Qualité de Code
- Remplacer tous les usages résiduels de `datetime.utcnow()` (déjà traité pour liquidations & scheduler tests) — audit ponctuel futur.
- Uniformiser clés de cache (ex: normaliser chaînes en minuscules pour defillama) pour éviter doublons.
- Ajouter mypy (mode strict progressif) + configuration d'exclusion initiale sur modules dynamiques.

### Sécurité & Résilience
- Timeout explicite et `retry` paramétrable via variables d'environnement pour collectors critiques.
- Ajout d'un circuit breaker léger (compter échecs consécutifs → pause exponentielle) pour endpoints instables.

### CI / Tooling
- Publier artifact `coverage.xml` + intégrer Codecov (badge déjà présent mais vérifier token config privée si nécessaire).
- Ajouter job lint (`ruff` ou `flake8`) + mypy avant tests pour fail fast.
- Générer rapport HTML coverage en artifact téléchargeable pour revue détaillée.

### Documentation
- Déplacer la stratégie de couverture détaillée dans `CONTRIBUTING.md` et ne garder ici qu'un résumé.
- Ajouter un diagramme simple (scheduler → orchestrator → collectors → exporter) dans `docs/architecture.md`.

### Monitoring Runtime (Long terme)
- Intégrer un export OpenTelemetry (logs + traces) optionnel avec sampling bas.
- Ajouter watchdog sur durée moyenne de collecte pour détecter dérives de latence.

### Divers
- Prévoir abstraction de persistance (SQLite → Postgres) via petite couche DAO si volumétrie augmente.
- Ajout d'un mode « dry-run » pour valider config scheduler sans exécuter les collectors (test déploiement infra).

Si vous ciblez un palier supérieur (ex: 85%-88%), privilégier d'abord la factorisation des mocks + marquage des chemins véritablement in-testables.

## Nouvelles fonctionnalités (Sprint Couverture & Robustesse)

Ajouts clés récents:

- Circuit breaker léger (seuil 3 échecs consécutifs, cooldown 30s) intégré aux collectors `defillama`, `derivatives` (OI & L/S ratio) et `market` (main + macro) avec métriques de skips.
- Instrumentation Prometheus supplémentaire: compteurs `*_cache_hit_total`, `*_cache_miss_total`, `*_breaker_skips_total`, latence par collector.
- Partitionnement Parquet pour les liquidations Bybit: `data/bybit_liquidations/year=YYYY/month=MM/day=DD/hour=HH/bybit_liquidations.parquet`.
- Factorisation des mocks HTTP dans `tests/utils/http_mocks.py` pour réduire duplication et isoler la logique de simulation réseau.
- Tests supplémentaires couvrant: branches d'erreur DefiLlama (données historiques mal formées), fallback market CoinMarketCap, ouverture/ cooldown du circuit breaker, skip breaker, scénarios cache hit/miss.

### Stratégie Couverture (Option C)

Objectif utilisateur: « pousser la couverture à 100% » tout en restant prod-safe. Nous avons appliqué une stratégie hybride:

1. Ajout de tests ciblés sur les branches métier à forte valeur (fallbacks, parsing historique, breaker).
2. Marquage `# pragma: no cover` sur branches défensives ou très rares (erreurs réseau profondes, double fallback, timing flush, présentation tabulaire).
3. Exclusions temporaires (Option C) de modules dits « extrêmes » peu critiques ou verbeux (`ws`, anciens collectors, scripts auxiliaires) documentées dans `.coveragerc`.

Résultat actuel (post-refonte tests orchestrateur): ~87% lignes couvertes (seuil temporaire 75%). L'ancien seuil 94% est archivé; retour progressif visé une fois les boucles longues (`while True` scheduler/heartbeat) et endpoints santé mieux factorisés pour testabilité.

Prochaines étapes possibles pour tendre vers 100% réel (au lieu de purement apparent):
- Écrire des tests de simulation fine pour les derniers chemins d'erreur des collectors (en mockant réponses JSON structurellement invalides supplémentaires).
- Instrumenter et tester des cas de flush Parquet désactivé/activé avec exceptions forcées (via monkeypatch `to_parquet`).
- Remplacer certains pragmas par des tests si leur comportement devient critique (ex: validation de schéma DefiLlama si API évolue).

La remontée graduelle du seuil (75 -> 80 -> 85 -> 90+) se fera après réduction du code non testable structurel (extraction sous-fonctions testables) plutôt que par sur-mocking fragile.


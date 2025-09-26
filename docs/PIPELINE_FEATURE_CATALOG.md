# Catalogue des fonctionnalités et variables d'environnement du pipeline

Ce document dresse la liste exhaustive des fonctionnalités exposées par le pipeline et des variables d'environnement permettant de les configurer. Il sert également de référence pour l'interface Streamlit incluse (voir tools/streamlit_ui.py) qui permet de préparer un fichier .env cohérent.

Remarque: les types indiqués sont [bool|int|float|str]. Les bool s'interprètent avec les valeurs 1/0, true/false, yes/no, on/off (insensibles à la casse).

## Configuration globale
- CRYPTO_MONITOR_MODE [str, défaut "scheduler"]: Mode principal ("scheduler", "cli", etc.).
- ENABLE_SCHEDULER [bool, défaut 1]: Active le planificateur.
- SCHEDULER_CONFIG [str, défaut "scheduler/jobs.yaml"]: Chemin du fichier de jobs.
- RUN_JOBS_AT_START [bool, défaut 1]: Exécute les jobs immédiatement au démarrage.
- HEARTBEAT_SECS [int, défaut 60]: Période d'heartbeat en secondes.
- SCHEDULER_JITTER_PERCENT [int, défaut 10]: Jitter aléatoire appliqué aux jobs (%).
- RUN_ID [str, défaut vide]: Identifiant d'exécution propagé aux logs/métriques.
- CB_THRESHOLD [int, défaut 3]: Seuil d'ouverture du breaker interne (circuit breaker).
- CB_COOLDOWN_SECONDS [int, défaut 30]: Cooldown du breaker interne.

## Observabilité et santé
- ENABLE_METRICS [bool, défaut 0]: Expose le serveur Prometheus.
- METRICS_PORT [int, défaut 9300]: Port Prometheus.
- ENABLE_HEALTH [bool, défaut 1]: Expose le serveur de santé.
- HEALTH_PORT [int, défaut 9310]: Port santé.
- LOG_LEVEL [str, défaut "INFO"]: Niveau de logs structlog.
- ENABLE_FILE_LOGS [bool, défaut 1]: Active les logs fichier.
- LOGS_DIR [str, défaut "logs"]: Dossier de logs.

## HTTP: retry et breaker
- RETRY_HTTP_ENABLED [bool, défaut 1]: Active le retry HTTP global.
- RETRY_HTTP_MAX [int, défaut 3]: Nombre d'essais.
- RETRY_HTTP_BACKOFF_BASE [float, défaut 0.3]: Base du backoff exponentiel.
- RETRY_MAX_CUMULATIVE_SLEEP_SEC [float, défaut 0]: Budget cumulé de sommeil (0 illimité).
- HTTP_BREAKER_WINDOW [float, défaut 30]: Fenêtre de détection des 429 (s).
- HTTP_BREAKER_THRESHOLD [int, défaut 5]: Nombre d'évènements 429 dans la fenêtre pour ouvrir.
- HTTP_BREAKER_COOLDOWN [float, défaut 20]: Durée d'ouverture (s) avant ré-essais.
- RETRY_FORCE_THREAD [bool, défaut 0]: Force un mode thread pour certains collectors (defillama, legacy compat).
- FORCE_HTTP_FACADE [bool, défaut 0]: Force l'usage de la façade HTTP unifiée (observabilité renforcée).
- DRY_RUN_FACADE [bool, défaut 0]: Mode dry-run pour la façade HTTP (ne fait que simuler).

## Collectors et fallbacks
- ENABLE_BINANCE_SPOT_FALLBACK [bool, défaut 0]: Active fallback spot Binance dans market.
- ENABLE_BINANCE_MACRO_FALLBACK [bool, défaut 0]: Active fallback macro Binance.
- ENABLE_BINANCE_OI_FALLBACK [bool, défaut 0]: Active fallback Open Interest (dérivés).
- BINANCE_HTTP_TIMEOUT [float, défaut 5]: Timeout HTTP côté Binance collector.
- BINANCE_API_KEY [str, défaut vide]: Clé API Binance (si nécessaire pour endpoints). 
- MARKET_USE_FACADE [bool, défaut 0]: Force le collector market à passer par la façade (compat).
- CMC_API_KEY [str, défaut vide]: Clé CoinMarketCap (si utilisée par des scripts legacy/exports).
- ETHERSCAN_API_KEY [str, défaut vide]: Clé Etherscan (si utilisée par des scripts legacy/exports).

## Intervalles du scheduler (secondes)
- COLLECTOR_INTERVAL_MARKET [int, défaut 300]
- COLLECTOR_INTERVAL_DEFILLAMA [int, défaut 900]
- COLLECTOR_INTERVAL_ONCHAIN [int, défaut 1800]
- COLLECTOR_INTERVAL_DERIVATIVES [int, défaut 300]
- COLLECTOR_INTERVAL_SENTIMENT [int, défaut 3600]

## LLM (fournisseurs)
- OPENAI_API_KEY [str, défaut vide]
- OPENAI_MODEL [str, défaut "gpt-4o-mini"]
- OPENAI_DAILY_LIMIT [int, défaut 500]
- OPENROUTER_API_KEY [str, défaut vide]
- OPENROUTER_MODEL [str, défaut "openrouter/auto"]
- OPENROUTER_DAILY_LIMIT [int, défaut 500]
- OLLAMA_HOST [str, défaut "http://127.0.0.1:11434"]
- OLLAMA_MODEL [str, défaut "llama3.1"]
- OLLAMA_DAILY_LIMIT [int, défaut 10000]

## API FastAPI
- API_DOCS_ENABLED [bool, défaut 1]: Active /docs et /redoc.
- API_CORS_ENABLED [bool, défaut 0]
- API_CORS_ORIGINS [str, défaut vide]: Liste d’origines séparées par des virgules.
- API_GZIP_ENABLED [bool, défaut 0]
- API_GZIP_MIN_SIZE [int, défaut 500]
- API_MAX_BODY_BYTES [int, défaut 0]: 0 = illimité (conseillé: fixer un plafond en prod).
- API_WRITE_KEY [str, défaut vide]: Clé requise pour les endpoints d’écriture.
- API_RATE_LIMIT_PER_MIN [int, défaut 60]
- API_RATE_LIMIT_BACKEND [str, défaut vide]: "memory" ou "redis" (si supporté par configuration).
- REDIS_URL | API_REDIS_URL [str]: URL Redis si backend choisi.
- API_ENFORCE_HTTPS [bool, défaut 0]: Exiger HTTPS (autorise localhost en clair).
- API_READ_MAX_AGE [int, défaut 0]: Cache-Control max-age côté lecture.
- API_VERSION [str, défaut hérité APP_VERSION]: Version exposée.
- API_BUILD_DATE [str, défaut now]: Date de build exposée.
- API_GIT_SHA [str, défaut GIT_SHA]: SHA exposé.

## Export / reporting
- EXPORT_DIR [str, défaut "exports"]: Dossier pour CSV et manifest.

## Maintenance et purge
- LIQ_RETENTION_DAYS [int, défaut 30]: Rétention des données de liquidations.
- LIQ_PURGE_DRY_RUN [bool, défaut 0]: N'efface pas réellement (compte uniquement).
- DB_FRAGMENTATION_VACUUM_THRESHOLD [float, défaut 0.15]: Fragmentation au-delà de laquelle VACUUM.
- FORCE_VACUUM [bool, défaut 0]: Force VACUUM même si seuil non atteint.
- MAINT_INTERVAL_SECONDS [int, défaut 86400]: Intervalle entre maintenances.

## Base de données / stockage
- SQLITE_JOURNAL_MODE [str, défaut "WAL"]
- SQLITE_SYNCHRONOUS [str, défaut "NORMAL"]
- SQLITE_CACHE_SIZE [str, défaut non défini]: Exemple "-20000"

## Build et exécution
- APP_VERSION | VERSION [str, défaut "dev"]
- GIT_SHA [str, défaut "unknown"]
- STATE_DIR [str, défaut "data"]: Dossier d’état du scheduler.
- TASK_ERROR_RATE_WARN [float, défaut 0.2]: Seuil d’alerte taux d’erreurs job.
- TASK_ERROR_RATE_MIN_COUNT [int, défaut 5]: Nombre minimal d’exécutions considérées.
- BREAKER_CRITICAL_LIST [str, défaut "market,deriv_oi,onchain_txcount"]: Liste de breakers critiques.
- BREAKER_OPEN_GRACE_SECONDS [float, défaut 120]: Grace period après ouverture.

## Outils et divers
- SMOKE_API_PORT [int, défaut 9322]: Port du script de smoke test API.
- SBOM_OUTPUT_DIR [str, défaut "sbom"]
- SBOM_FORMATS [str, défaut "JSON"]: Ex: "JSON,SPDX".

---

# Surfaces fonctionnelles (principales)

## Collecte
- pipeline.collectors.market:
  - fetch_market(symbol) → MarketSnapshot
  - fetch_macro(...) → MacroRecord(s) (CoinGecko → CMC fallback)
  - Fallbacks pilotés par ENABLE_BINANCE_* et MARKET_USE_FACADE
- pipeline.collectors.binance:
  - fetch_binance_spot_price, fetch_binance_futures_oi, fetch_binance_funding
- pipeline.collectors.derivatives, defillama, onchain (selon fichiers présents)
- pipeline.collectors.bybit_ws:
  - BybitWSService(symbols, ws_url?, db_path, parquet_dir, flush_size, flush_interval)
  - Collecteur temps-réel liquidations (Prometheus inclus)

## Orchestration
- pipeline.orchestrator: run_fallback_chain(...), exécutions parallèles
- pipeline.scheduler: CryptoScheduler, intervals via COLLECTOR_INTERVAL_*

## HTTP unifié
- pipeline.http.fetch_json / async_fetch_json: retry/breaker central
- pipeline.http_wrappers: logique fine (classification, métriques, breaker 429)

## LLM
- pipeline.llm.client.ClientLLM + providers (OpenAI, OpenRouter, Ollama, mock)

## Exports
- pipeline.export_utils: export_csv_rows, export_latest_and_timestamped

## Observabilité / santé
- pipeline.metrics.*: métriques Prometheus
- pipeline.health: heartbeat + serveur santé (JSON + ready)

## Maintenance
- pipeline.purge_job: purge_liquidations + register_purge_job
- pipeline.maintenance: vacuum/metrics

---

# Streamlit UI (squelette)

Un squelette d’interface Streamlit mappant ces variables est fourni: `tools/streamlit_ui.py`.
- Objectif: préparer visuellement une configuration et produire un .env à copier.
- Sécurité: par défaut, aucune requête réseau n’est effectuée; l’app est un configurateur.
- Lancement:
  1) Installer streamlit (optionnel): `pip install streamlit`
  2) Exécuter: `streamlit run tools/streamlit_ui.py`

Dans l’UI:
- Sidebar: actions (réinitialiser, générer .env), aperçu RUN_ID, ports métriques/santé
- Sections: Global, Scheduler, HTTP/Breaker, Collectors, LLM, API, Export, Maintenance, DB/Storage, Build.
- Bouton "Générer .env" copie le texte dans un textarea prêt à enregistrer.

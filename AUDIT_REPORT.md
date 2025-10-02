# Audit technique & fondamental – Monitoring Crypto

## 1) Description fonctionnelle & architecture actuelle

- Collecte multi-sources (market, dérivés, on-chain, defi, sentiment) → export CSV normalisé → analyses (signals + LLM) → persistance JSON → (option) émission d’événements (JSONL).
- Modules clés:
  - pipeline/collectors/* (market, binance, derivatives, defillama, onchain, sentiment)
  - pipeline/export_utils.py (normalisation CSV + manifest)
  - pipeline/analysis/* (dataset, signals, runner, llm_exec, persist, events)
  - pipeline/rate_limit.py, http_wrappers.py (retry, breaker, façade)
  - main.py, cli_collect_once.py (orchestration)
- Flux: scheduler → collect → export → analyse auto (flags) → events.

## 2) Inventaire APIs & dépendances

- Voir docs/APIs.md (tableau détaillé, liens officiels). Clés possibles: CMC_API_KEY (option), TWELVEDATA_API_KEY, ALPHAVANTAGE_API_KEY.
- Dépendances Python: voir requirements.txt (httpx, prometheus_client, pandas, diskcache, etc.). Pas de JS.
- Scripts: cli_collect_once.py, cli_analysis.py, ws_smoke_test.py.

## 3) Quotas & risques (citations)

- Messari (AI): Free ≈ 2 req/j – docs.messari.io
- Twelve Data: ≈ 800 req/j – twelvedata.com/docs
- Alpha Vantage: ≈ 25 req/j – alphavantage.co/documentation
- Blockchair: soft 5 req/s, hard 30 req/min – blockchair.com/api/docs
- CoinGecko: ≈ 30/min (démo/public) – coingecko.com/api/documentation
- Binance: rate limits par poids – binance-api

## 4) Anomalies & améliorations (priorisées)

- Urgent: Centraliser le set des gauges façade AVANT cache-hit (fait pour deriv_funding/lsr).
- Important: Externaliser règles signaux (YAML) et ajouter alerting (webhook) – en plan.
- Optionnel: Ajouter parsers ISO → unix pour macro indices (td/av) pour timestamps homogènes.

## 5) Conception intégration macro + on-chain

- Architecture cible: collector → normalizer → cache TTL → store (CSV/JSON) → analyzer AI.
- Interfaces: chaque collector retourne {timestamp, asset, metric_name, value, source, confidence_score}.
- Rate limits: décorateur via pipeline/rate_limit; backoff via http_wrappers (tenacity) déjà présent pour on-chain; breaker via circuit_breaker.
- Fallbacks: ordre documenté dans chaque collector; chaînes primary → secondary, marquage FALLBACK_* metrics.

## 6) Patchs inclus (feature flags, non-invasifs)

- Nouveau: pipeline/collectors/macro_indices.py (ENABLE_MACRO_INDICES=1)
- Nouveau: pipeline/collectors/mvrv.py (ENABLE_MVRV_COLLECTOR=1)
- export_job: branche ces collectors si flags actifs.

## 7) Tests & sanity

- Tests existants passent (pytest). Ajouter tests unitaires pour nouveaux collecteurs avec mocks HTTP.
- Sanity: ajouter compare Binance vs CoinGecko (±0.5%), freshness indices < 24h (TODO outil tools/check_freshness.py).

## 8) Sécurité / secrets

- Clés en .env/.secrets; rotation recommandée; pas de commit de secrets.
- Scrubbing logs pour tokens (déjà prudent, pas de headers de secrets loggés).

## 9) Exploitation & monitoring

- Métriques Prometheus exposées si ENABLE_METRICS=1 (cf. pipeline/metrics/*). Ajouter freshness gauge last_seen par collector (TODO).
- COMMANDES.md livré pour install/usage.

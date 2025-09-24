# Observabilité & Métriques

Ce document recense les métriques Prometheus exposées par la pipeline, leur sémantique, les labels et des exemples de requêtes / alertes.

Nouveau: l'architecture des métriques est désormais segmentée (voir `docs/ARCHITECTURE_METRICS.md`) au lieu d'un module monolithique. Tous les symboles restent importables via `from pipeline import metrics`.

## Sommaire
- [1. Principes](#1-principes)
- [2. Collectors & Fallbacks](#2-collectors--fallbacks)
- [3. Export & Buffer](#3-export--buffer)
- [4. Base de données](#4-base-de-données)
- [5. Circuit Breakers](#5-circuit-breakers)
- [6. Latence & Performance](#6-latence--performance)
- [7. Health & Heartbeat](#7-health--heartbeat)
- [8. Purge & Maintenance](#8-purge--maintenance)
- [9. Exemples PromQL](#9-exemples-promql)
- [10. Alerting recommandé](#10-alerting-recommandé)

---
## 1. Principes
Toutes les métriques sont nommées en snake_case et suivent un schéma stable. Les labels importants:
- `collector`: identifie un collecteur logique (`macro`, `market`, `deriv_oi`, `deriv_funding`, `deriv_liq`, ...)
- `status`: `success` ou `error`
- `tier`: profondeur dans la chaîne de fallback (1 = primaire)

Les métriques sont conçues pour:
1. Diagnostiquer la santé (succès/erreurs)
2. Visualiser la profondeur et la latence des fallbacks
3. Superviser l'efficacité des exports & maintenance

---
## 2. Collectors & Fallbacks
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `collector_runs_total` | Counter | collector,status | Exécutions globales d'un collecteur (avec instrumentation explicite). |
| `fallback_invocations_total` | Counter | collector,status | Nombre total d'activation de fallback (agrégé, toutes profondeurs confondues). |
| `fallback_tier_invocations_total` | Counter | collector,tier,status | Comptage par niveau (1 = primaire). Permet de voir la fréquence relative des fallback tiers 2/3+. |
| `fallback_tier_latency_seconds` | Histogram | collector,tier,status | Latence par tier avec buckets (0.05 à 30s). Utile pour comparer lenteur des fallbacks vs primaire. |
| `fallback_chain_depth` | Gauge | collector | Dernière profondeur atteinte dans une exécution (1=primaire). Réinitialisée implicitement par nouvelles observations. |

---
## 3. Export & Buffer
| Metric | Type | Labels | Note |
|--------|------|--------|------|
| `pipeline_exports_total` | Counter | status | Succès/erreurs d'exports CSV. |
| `pipeline_export_rows_total` | Counter | status | Lignes exportées (compte cumulatif). |
| `writer_buffer_length` | Gauge | writer | Taille courante du buffer. |
| `writer_last_flush_timestamp` | Gauge | writer | Epoch du dernier flush. |
| `flush_operations_total` | Counter | writer,status | Nombre de flush (success/noop). |
| `flush_failures_total` | Counter | writer,phase | Échecs flush (phase du point de défaillance : ex `write`, futur `parquet`). |

Notes:
- `flush_failures_total` n'est incrémenté qu'en cas d'exception non récupérée sur la séquence de persistance. Le label `phase` vaut actuellement `write` (insertion DB + agrégations); des phases supplémentaires (ex: `parquet`) pourront être ajoutées si on distingue les étapes.

---
## 4. Base de données
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `db_file_size_bytes` | Gauge | — | Taille du fichier SQLite principal. |
| `db_liquidations_rows` | Gauge | — | Nombre de lignes agrégées. |
| `purge_operations_total` | Counter | table,status,mode | Purges réalisées. |
| `db_vacuum_duration_seconds` | Gauge | — | Durée du dernier vacuum. |
| `db_page_count` | Gauge | — | Pages totales. |
| `db_freelist_pages` | Gauge | — | Pages libres. |
| `db_fragmentation_ratio` | Gauge | — | Ratio freelist/total pages. |
| `maintenance_next_run_timestamp` | Gauge | — | Prochain cycle planifié maintenance (purge+vacuum). |

---
## 5. Circuit Breakers

Deux familles distinctes coexistent:
1. Breaker léger HTTP (spécifique 429) — scope endpoint normalisé.
2. Breakers génériques (infrastructure) — scope logique nommé (`breaker`).

### 5.1 Breaker léger HTTP 429
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_breaker_opens_total` | Counter | endpoint | Ouvertures du breaker léger (seuil 429 atteint). |
| `http_breaker_skips_total` | Counter | endpoint | Requêtes court-circuitées car breaker encore ouvert. |
| `http_breaker_state` | Gauge | endpoint | 1=open, 0=closed (dernier état observé). |
| `http_breaker_open_seconds` | Gauge | endpoint | Âge en secondes depuis l'ouverture courante (0 si fermé). |

Notes:
- `endpoint` est la version normalisée (voir endpoint_label) réduisant cardinalité.
- `http_breaker_open_seconds` est remis à 0 à l'ouverture, retombe à 0 lors de la fermeture.

### 5.2 Circuit breakers génériques
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `circuit_breaker_open_total` | Counter | breaker | Ouvertures cumulées breaker générique. |
| `circuit_breaker_skips_total` | Counter | breaker | Skips dus à breaker générique ouvert. |
| `circuit_breaker_state` | Gauge | breaker | 1=open, 0=closed. |
| `circuit_breaker_open_seconds` | Gauge | breaker | Âge (s) depuis ouverture (0 si fermé). |
| `circuit_breaker_last_open_timestamp` | Gauge | breaker | Timestamp epoch dernière ouverture. |
| `circuit_breaker_resets_total` | Counter | breaker | Transitions open->closed cumulées. |

Roadmap: consolidation potentielle si unification sémantique (non prioritaire).

---
## 6. Latence & Performance
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `collector_duration_seconds` | Histogram | collector,status | Durée globale d'un collecteur (regroupe opération complète). |
| `fallback_tier_latency_seconds` | Histogram | collector,tier,status | (Déjà listé) granularité par tier. |
| `defillama_latency_seconds` | Summary | — | Latence spécifique DefiLlama async (tenacity). |
| `writer_flush_latency_seconds` | Histogram | writer,status | Latence mur-à-mur d'un flush (succès ou erreur). Buckets: 0.01,0.025,0.05,0.1,0.25,0.5,1,2.5,5,10. |

---
## 7. Health & Heartbeat
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `heartbeat_ticks_total` | Counter | source | Pulsations périodiques (scheduler/loop). |
| `health_requests_total` | Counter | endpoint,status | Requêtes entrantes sur endpoints de health. |

---
## 8. Purge & Maintenance
Voir section DB: purge & vacuum déjà instrumentés.

---
## 9. Exemples PromQL
### Taux d'erreurs (global)
```
sum by(collector) (rate(collector_runs_total{status="error"}[5m]))
/
sum by(collector) (rate(collector_runs_total{status="success"}[5m]) + rate(collector_runs_total{status="error"}[5m]))
```

### Ratio fallback vs primaire (tier 2 macro)
```
rate(fallback_tier_invocations_total{collector="macro",tier="2",status="success"}[15m])
/
rate(fallback_tier_invocations_total{collector="macro",tier="1",status="success"}[15m])
```

### Latence P95 primaire vs fallback funding
```
histogram_quantile(0.95, sum by(le) (rate(fallback_tier_latency_seconds_bucket{collector="deriv_funding",tier="1",status="success"}[10m])))
,
histogram_quantile(0.95, sum by(le) (rate(fallback_tier_latency_seconds_bucket{collector="deriv_funding",tier="2",status="success"}[10m])))
```

### Latence P95 flush writer (ex: liquidations Bybit)
```
histogram_quantile(0.95, sum by(le) (rate(writer_flush_latency_seconds_bucket{writer="bybit_liq",status="success"}[15m])))
```

### Profondeur moyenne des fallbacks
```
avg_over_time(fallback_chain_depth{collector="deriv_oi"}[30m])
```

### Ouvertures breaker récentes
```
increase(circuit_breaker_open_total[1h])
```

### Export rows par minute
```
rate(pipeline_export_rows_total{status="success"}[5m])
```

### Fragmentation SQLite
```
(db_freelist_pages / db_page_count) * 100
```

### Décision vacuum vs fragmentation (ratio>0.15)
```
increase(db_vacuum_duration_seconds[1d]) > 0 AND max_over_time(db_fragmentation_ratio[1d]) > 0.15
```

---
## 10. Alerting recommandé (exemples)
| Règle | Condition | Délai | Sévérité |
|-------|-----------|-------|----------|
| Erreur collector anormale | taux erreurs > 5% sur 10m | 5m | warning |
| Breaker ouvert prolongé | circuit_breaker_state==1 & circuit_breaker_open_seconds > 180 | 3m | critical |
| Pas de macro primaire | increase(fallback_tier_invocations_total{collector="macro",tier="1",status="success"}[30m]) == 0 | 30m | warning |
| Explosion fallback tier2 | rate(fallback_tier_invocations_total{collector="deriv_funding",tier="2",status="success"}[15m]) >  rate(fallback_tier_invocations_total{collector="deriv_funding",tier="1",status="success"}[15m]) | 15m | warning |
| Export bloqué | increase(pipeline_exports_total{status="success"}[20m]) == 0 | 20m | critical |
| Flush erreurs élevé | (increase(flush_failures_total[10m]) > 0) AND (increase(flush_operations_total{status="success"}[10m]) == 0) | 10m | critical |
| Flush latence dégradée | histogram_quantile(0.95, sum by(le) (rate(writer_flush_latency_seconds_bucket{writer="bybit_liq",status="success"}[10m]))) > 2 | 10m | warning |

Exemple de règle Prometheus (YAML):
```yaml
- alert: HighCollectorErrorRate
  expr: |
    (sum by (collector) (rate(collector_runs_total{status="error"}[10m]))) /
    (sum by (collector) (rate(collector_runs_total{status="error"}[10m]) + rate(collector_runs_total{status="success"}[10m]))) > 0.05
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Taux d'erreurs élevé pour {{ $labels.collector }}"
    description: ">5% d'erreurs sur 10 minutes."
```

---
## 11. Taxonomie des erreurs collecteurs

Les collecteurs lèvent désormais (directement ou via mapping) une série d'exceptions
typiques normalisées en catégories stables. La métrique
`collector_error_types_total{collector="...", error_type="..."}` permet des analyses
fines (alerting ciblé, corrélation fournisseur, saturation).

| Catégorie | Définition | Exemples de sources | Stratégie / Remédiation |
|-----------|------------|---------------------|-------------------------|
| `network` | Échec de connexion / transport | ConnectionError, httpx.RequestError | Vérifier réseau, DNS, proxy, latence. |
| `timeout` | Délai dépassé (client) | httpx.TimeoutException | Augmenter timeout ou optimiser fournisseur. |
| `rate_limit` | Quota fournisseur atteint | HTTP 429 Binance/CMC | Backoff, clés dédiées, caching agressif. |
| `not_found` | Ressource absente / 404 | HTTP 404 (symbol inconnu) | Valider symbol, fallback alt symbol. |
| `upstream` | Erreur serveur 5xx | 502/503/504 | Retry exponentiel, basculer fallback. |
| `schema` | Format inattendu / parsing | KeyError, JSON structure divergente | Mettre à jour parseur, surveiller breaking changes. |
| `empty_data` | Réponse vide jugée anormale | Liste vide funding, dict vide | Considérer fallback ou marquer source dégradée. |
| `unknown` | Non classé | Exceptions non mappées | Inspecter logs, ajouter classification future. |

Exemples PromQL additionnels:

Top erreurs sur 30m:
```
topk(5, increase(collector_error_types_total[30m]))
```

Distribution par type (macro) sur 1h:
```
sum by(error_type) (increase(collector_error_types_total{collector="macro"}[1h]))
```

Taux rate limit vs total erreurs (macro):
```
increase(collector_error_types_total{collector="macro",error_type="rate_limit"}[15m])
/
increase(collector_error_types_total{collector="macro"}[15m])
```

Détection d'un nouveau schéma inattendu (hausse brutale schema):
```
increase(collector_error_types_total{error_type="schema"}[10m]) > 5
```

## 12. Références complémentaires
- Schéma base: voir `SCHEMA_DB.md`
- Modèle de menace: `THREAT_MODEL.md`
- Sécurité & SBOM: `README_SECURITY.md`

## 13. Roadmap courte observabilité
- Séparer phase flush parquet vs write.
- Ajouter gauge last_flush_duration_seconds.
- Dashboard Grafana standard packagé.

## 14. Notes d’implémentation
---
Fin du document.

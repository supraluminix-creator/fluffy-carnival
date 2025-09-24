# Architecture des métriques

Ce document décrit la segmentation des métriques Prometheus introduite après la refactorisation du module monolithique `pipeline/metrics.py`.

## Objectifs
- Réduction du couplage et lisibilité accrue.
- Ajout de nouvelles métriques sans risquer de collisions ou de complexifier le module principal.
- Rétrocompatibilité totale: tous les symboles restent ré-exportés via `pipeline.metrics`.
- Idempotence: aucune double inscription des collectors Prometheus (gestion via helpers internes `_counter/_gauge/_histogram`).

## Segmentation
| Sous-module | Rôle | Exemples de métriques |
|-------------|------|------------------------|
| `metrics.collectors` | Exécution et fallbacks des collecteurs | `COLLECTOR_RUNS_TOTAL`, `COLLECTOR_DURATION_SECONDS`, `FALLBACK_TIER_LATENCY_SECONDS` |
| `metrics.export` | Exports CSV & writer/flush | `EXPORTS_TOTAL`, `WRITER_FLUSH_LATENCY_SECONDS` |
| `metrics.db` | Santé SQLite (taille/fragmentation/purge) | `DB_FILE_SIZE_BYTES`, `DB_FRAGMENTATION_RATIO` |
| `metrics.system` | Heartbeat, health, maintenance, retries HTTP | `HEARTBEAT_TICKS_TOTAL`, `MAINTENANCE_CYCLES_TOTAL` |
| `metrics.breakers` | Breakers HTTP légers + circuit breakers | `HTTP_BREAKER_OPENS_TOTAL`, `CIRCUIT_BREAKER_STATE` |
| `metrics.errors` | Classification d'erreurs collectors | `COLLECTOR_ERROR_TYPES_TOTAL` |

## Règles d'ajout
1. Choisir le sous-module thématique. Si aucune catégorie ne convient, discuter avant de créer un nouveau fichier.
2. Préfixer les noms selon le domaine (`collector_`, `db_`, `writer_`, `http_`, `circuit_breaker_`, etc.).
3. Utiliser les helpers internes `_counter/_histogram/_gauge` pour assurer l'idempotence (évite ValueError lors de re-chargements en tests).
4. Ajouter le symbole dans `__all__` du sous-module puis vérifier qu'il est bien ré-exporté par `metrics/__init__.py` si exposition publique nécessaire.
5. Mettre à jour / ajouter un test de fumée si l'API publique s'élargit (adapter `tests/test_metrics_imports_stable.py`).
6. Documenter brièvement la sémantique de la métrique dans un commentaire au point de déclaration si non évidente.

## Stratégie d'évolution
- Phase future: ajout de métriques de qualité de données export (compteurs rejets validation, bornes sur valeurs). 
- Possibilité d'introduire un sous-module `metrics.quality` le moment venu.
- Une fois la transition assimilée, `monitoring.py` pourra être définitivement retiré (actuellement façade de compatibilité).

## Anti-patterns évités
- Monolithe >500 lignes difficile à relire.
- Collisions silencieuses de noms lors de reload tests.
- Mélange de niveaux de granularité (latence HTTP, writer, fallback, DB) dans un même bloc.

## Backward compatibility
L'import historique:
```python
from pipeline.metrics import EXPORTS_TOTAL
```
reste valide. Les chemins internes (`pipeline.metrics.collectors`) sont désormais supportés pour un ciblage plus précis.

## Test de stabilité
Le fichier `tests/test_metrics_imports_stable.py` agit comme contrat d'API: échec si un symbole critique disparaît.

## Checklist ajout d'une métrique
- [ ] Choix sous-module adéquat
- [ ] Nom clair, snake_case, préfixé domaine
- [ ] Sélection type (Counter/Gauge/Histogram) justifiée
- [ ] Ajout via helper idempotent
- [ ] Ajout à `__all__`
- [ ] (si public) vérification export par namespace principal
- [ ] Test de fumée mis à jour
- [ ] Documentation courte (ligne de commentaire)

## Data Quality Metrics (Export)
Deux compteurs ont été introduits pour observer la qualité des lignes exportées et mesurer les pertes:

| Métrique | Labels | Description |
|----------|--------|-------------|
| `pipeline_export_row_rejections_total` | `reason` | Nombre de lignes rejetées avant écriture CSV. `reason` actuel: `pydantic` (validation schéma), `negative_value` (valeur numérique < 0 filtrée). |
| `pipeline_export_value_negative_total` | `metric_name` | Nombre d'occurrences où une métrique a produit une valeur négative rejetée. Permet d'identifier les séries à dérive ou erreurs de signe. |

Principes:
- Les lignes rejetées ne comptent pas dans `pipeline_export_rows_total`.
- Une valeur négative déclenche deux incréments: un par-métrique (`pipeline_export_value_negative_total`) et un rejet global (`pipeline_export_row_rejections_total{reason="negative_value"}`).
- Les validations Pydantic (ex: contrainte de domaine sur `confidence_score`) incrémentent `reason="pydantic"`.

Exemples PromQL:
```promql
# Ratio de lignes rejetées
sum(increase(pipeline_export_row_rejections_total[5m])) / sum(increase(pipeline_export_rows_total[5m]))

# Top métriques produisant des valeurs négatives
sum by (metric_name) (increase(pipeline_export_value_negative_total[15m]))
```

Roadmap potentielle:
- Étendre taxonomy des `reason`: `missing_field`, `coercion_error`, `range_violation`.
- Histogramme de distribution des valeurs rejetées (si utile pour diagnostic).

---
Dernière mise à jour: ajout Data Quality Metrics.

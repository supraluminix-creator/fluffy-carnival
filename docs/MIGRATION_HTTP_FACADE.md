# Migration vers la façade HTTP unifiée (`pipeline.http`)

Objectif: centraliser tous les appels HTTP JSON (sync & async) via `fetch_json` / `async_fetch_json` pour :
- Réduire les divergences (retry, breaker, timeouts)
- Uniformiser instrumentation Prometheus
- Simplifier les tests (un point de patch)
- Offrir un bouton rouge global (`FORCE_HTTP_FACADE`) pour éliminer d'un coup les chemins legacy en production si besoin

## État actuel (après introduction du flag global FORCE_HTTP_FACADE)

| Module Collector | Mode normal (legacy par défaut) | Opt-in spécifique | Mode forcé (`FORCE_HTTP_FACADE=1`) | Remarques |
|------------------|----------------------------------|-------------------|--------------------------------------|-----------|
| defillama        | async façade si RETRY_HTTP_ENABLED=1 sinon legacy async | N/A | Toujours façade | Historique + chaînes passent façade en forced même retry off |
| derivatives OI   | Façade (déjà migré) | N/A | Mode DRY-RUN (`DRY_RUN_FACADE=1`) | OI: 100% façade |
| derivatives funding | Legacy direct Bybit (AsyncClient) | N/A | Façade | Plus d'incrément legacy en forced |
| derivatives long/short | Legacy direct Bybit | N/A | Façade | Idem funding |
| market orchestré | Façade | N/A | Façade | Stable |
| market sync      | Legacy httpx direct | MARKET_USE_FACADE=1 | Façade forcée (aucun fallback legacy) | Incrémente legacy uniquement hors opt-in/forced |
| binance spot / oi / funding | Legacy direct | N/A | Façade | Instrumentation legacy inactive en forced |
| sentiment        | Legacy direct (AVANT) | N/A | Façade | Migré (forced branche -> façade, legacy instrumenté hors forced) |
| onchain txcount  | Legacy direct (requests/httpx) | N/A | Gauges dry-run=1 | Migré (sync & async basculent, legacy compteur hors forced) |
| onchain hashrate | Legacy direct (httpx async) | N/A | Façade | Migré (retry via façade, plus de fallback legacy en forced) |
| onchain sopr     | Legacy direct (requests) | N/A | Façade | Migré (fetch_json sous forced, legacy compteur hors forced) |

Collectors restants à auditer: retombées legacy market sync (fallback CMC en mode non forced), helpers obsolètes, rationalisation tests.

## Hiérarchie des flags
1. `FORCE_HTTP_FACADE=1` (force tous les collectors compatibles sur la façade, désactive incréments legacy)
2. Sinon, flags de module (ex: `MARKET_USE_FACADE=1`)
3. Sinon, chemin legacy instrumenté (compteur `legacy_http_usage_total{collector=...}`)

## Phases & statut
1. DefiLlama migration initiale – DONE
2. Derivatives OI – DONE
3. Macro orchestré – DONE
4. Market sync opt-in – DONE
5. Flag global FORCE_HTTP_FACADE – DONE
6. Unification helpers internes (`_async_http_get_json`) – PENDING
7. Documentation complète (README hiérarchie + exemples) – PARTIEL
8. Nettoyage imports wrappers legacy – À PLANIFIER (après adoption complète)
9. Migration sentiment – DONE
10. Gauge forced + leak – DONE
11. Script audit HTTP – DONE
12. Migration on-chain (txcount/hashrate/sopr) – DONE
13. Helper central mark_legacy_http – DONE

## Instrumentation legacy
Compteur: `legacy_http_usage_total{collector="<name>"}`
Principe: incrément uniquement si le chemin legacy est réellement exécuté et pas déjà forcé/opt-in façade.
One-shot log: `legacy_http_usage_detected` par collector.
En mode forced : compteur stable (pas d'incrément) ⇒ facile à vérifier via un test de non-régression.

## Métriques façade & migration
Core:
- `http_retries_total{endpoint,final_status}`
- `http_retry_attempt_latency_seconds{endpoint,attempt}`
- `fallback_tier_invocations_total{collector,tier,status}`
Migration / Observabilité:
- `legacy_http_usage_total{collector}` (counter)
- `facade_forced{collector}` (gauge 0/1)
- `facade_forced_leak{collector}` (gauge 0/1) – fuite si legacy en mode forced (déclenchée via helper)

## Plan de rollback rapide
1. Désactiver `FORCE_HTTP_FACADE` (retour aux opt-ins individuels).
2. Désactiver les opt-ins spécifiques (ex: enlever `MARKET_USE_FACADE`).
3. Si bug persiste, rebrancher anciens wrappers (patch local minimal, les sections sont isolées).

## Dépréciation (prévisionnel mis à jour)
| Élément | Dépréciation cible | Retrait estimé |
|---------|--------------------|----------------|
| Appels directs httpx dans collectors migrés | Dès adoption >95% façade | +2 semaines |
| `get_json_with_retry` (thread) | Après unification totale | +4 semaines |
| `_async_http_get_json` (market helper) | Après Phase 6 | +4 semaines |
| Fallback CMC legacy (market) | Après 7j leak=0 | +2 semaines |

## Étapes suivantes immédiates (révisées)
- [x] Tests forced façade (market, defillama, binance, sentiment)
- [x] One-shot logs legacy
- [x] Compteur legacy stable sous forced
- [x] Gauge forced + gauge leak
- [x] Script d'audit HTTP (`python -m pipeline.dev.audit_http`)
- [ ] Test paramétré global (réduire duplication tests façade)
- [ ] README: section Résilience + hiérarchie des flags (compléter)
- [ ] DRY_RUN_FACADE (optionnel) : log sans appel upstream
- [ ] Suppression `_async_http_get_json`
- [ ] Retrait fallback CMC legacy (après observation)
- [ ] Alerte Prometheus sur `facade_forced_leak==1`

## Bonnes pratiques futures
-- Normaliser un label `endpoint` réduit (extraction domaine + path stable) pour limiter cardinalité.
-- Ajouter un gauge `facade_forced{collector}` (0/1) pour dashboards. – DONE
-- Script d'audit automatique listant collectors encore en legacy hors forced. – DONE
-- Gauge `facade_forced_leak{collector}` pour alerte régression. – DONE

---
## Helper `mark_legacy_http`

Centralise deux responsabilités:
1. Incrémenter `legacy_http_usage_total{collector}` quand un chemin non façadé est réellement emprunté.
2. Si `FORCE_HTTP_FACADE=1`, armer immédiatement `facade_forced_leak{collector}=1` (détection fuite / régression).

Test: `tests/test_facade_forced_leak_detection.py`.

---
Document maintenu automatiquement durant la migration façade.
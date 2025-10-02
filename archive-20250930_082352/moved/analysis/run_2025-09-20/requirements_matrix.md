# Matrice Exigences vs Implémentation (Squelette)

Date de création: 2025-09-20
Phase: Pré-runs (remplissage partiel après Phases C/D)

## Légende Statut
- P: Présent & conforme
- I: Incomplet / partiel
- A: Absent
- N/A: Non applicable dans le périmètre actuel

## Colonnes
| Domaine | Élément / Exigence | Source (Doc/Prompt) | Implémentation Réelle (Module / Fichier) | Fréquence Attendue | Fréquence Observée (après run) | Fallback Défini | Fallback Observé | Metrics Exposées | Couverture Tests (indicatif) | Statut | Commentaires / Gaps |
|---------|--------------------|---------------------|------------------------------------------|--------------------|-------------------------------|-----------------|------------------|------------------|-----------------------------|--------|---------------------|
| Collectors | DefiLlama données X | prompt_prod_safe / README | collectors/defillama.py | 5 min | (échec 404 sur ce cycle) | (à remplir) | (aucune donnée) | latency?, success?, error? | (à estimer) | I | Erreur 404 API; vérifier endpoint / chaîne |
| Collectors | Market data (prix) | prompts optimisation | collectors/market.py | 1 min | snapshot unique (macro) | CoinMarketCap fallback | non observé (cache hit) | latency?, success?, error? | (à estimer) | I | Besoin d'un run prolongé pour intervalle réel |
| Collectors | Derivatives OI | doc optimisation | collectors/derivatives.py | 5 min | snapshot unique (open_interest) | Binance fallback partiel | non exercé (cache hit) | latency?, success?, error? | (à estimer) | I | Vérifier fallback ratio long/short également |
| Résilience | Circuit Breaker global | prompts resilience | circuit_breaker.py & intégrations | n/a | n/a | Oui seuil=3 cooldown=30s | (événements à logger) | breaker_skips, errors | Tests partiels | P | Documenter dans CHANGELOG |
| Observabilité | Prometheus metrics | README (ajout) | instrumentation modules | n/a | n/a | n/a | n/a | listed counters/summaries | (à compléter) | I | Compléter liste exhaustive collectors |
| Stockage | Parquet partition liquidations | README | bybit_liquidations writer | À chaque flush | (à remplir) | n/a | n/a | flush_count? | Tests partiels | P | Ajouter metric flush_success |
| Documentation | CHANGELOG à jour features récentes | CHANGELOG.md | CHANGELOG.md | n/a | n/a | n/a | n/a | n/a | n/a | A | Mettre à jour section Resilience |
| Architecture | base_collector abstraction | prompts optimisation | (absent) | n/a | n/a | n/a | n/a | n/a | n/a | A | À introduire (quick win 2) |
| Gouvernance | Justification exclusions couverture | README + .coveragerc | README + .coveragerc | n/a | n/a | n/a | n/a | n/a | n/a | I | Ajouter doc dédiée si nécessaire |
| Données | Dictionnaire de données SQLite | (non spécifié) | data/crypto.db | n/a | n/a | n/a | n/a | n/a | n/a | A | Extraire schéma + typer colonnes |

## Post-Run (Cycle Unique 2025-09-20T18:52:09Z)

Résumé initial (voir artifacts/single_cycle_summary.json): 7 enregistrements collectés (macro, hashrate, txcount, sopr, open_interest, long_short_ratio, fear_greed). Durée ~2.67s.

Observations:
- DefiLlama TVL: échec HTTP 404 (chaîne "ethereum" via endpoint v2/chains?). À revalider / adapter.
- Tous les autres collectors: retours rapides (probables cache hits) → nécessite désactivation cache ou second run différé pour mesurer latence réelle & intervalle.
- Aucun fallback réellement exercé sur ce cycle (pas d'erreur primaire simulée).
- Export CSV généré: `latest_export.csv` + fichier horodaté avec RUN_ID.

Actions à prévoir avant validation des fréquences:
1. Forcer un second cycle après délai (ex: >60s) ou désactiver cache pour mesurer latence brute.
2. Simuler une panne API primaire (ex: dérivés) pour observer fallback effectif.
3. Corriger/mettre à jour l'appel DefiLlama (endpoint ou param). 
4. Compléter la colonne Metrics Exposées après inspection instrumentation réelle.

## Notes Méthodologiques
- Fréquence Observée sera renseignée à partir de timestamps collectés dans les logs lors d'un run unique (Phase C) puis confirmée si besoin sur plus longue fenêtre.
- Les colonnes Fallback Observé et Metrics Exposées seront validées par inspection du code + exposition /metrics (si endpoint ou scrap fichier). 
- Couverture Tests indicative: on consignera la présence de tests unitaires ou d'intégration spécifiques (O/N + brève note) plutôt que pourcentage global.

## Actions Post-Run (checklist)
- [ ] Capturer logs d'exécution (main run)
- [ ] Capturer logs WebSocket + événement de reconnexion
- [ ] Exporter schéma DB (PRAGMA) et ajouter section annexe
- [ ] Renseigner Fréquence Observée pour chaque collector
- [ ] Mettre à jour statut (P/I/A)
- [ ] Annoter gaps résiduels avec actions recommandées


# Top 3 Risques & Top 3 Quick Wins (Kickoff Audit)

Date: 2025-09-20
Phase: B (Synthèse documentaire, pré-exécution)

## Contexte
Synthèse issue de la revue des documents Markdown existants (README, prompts "prod-safe", optimisation collectors, architecture, sourcing timing, lint roadmap, etc.) avant toute exécution de pipeline ou WebSocket.

## Top 3 Risques (priorisés)
| # | Risque | Description | Impact | Probabilité | Sévérité | Indicateurs à collecter (Phases C/D) |
|---|--------|-------------|--------|-------------|----------|--------------------------------------|
| 1 | Fragmentation collectors / absence `base_collector` | Pas de couche commune pour retries, breaker, cache, metrics → duplication & divergence possible | Entretien, fiabilité, MTTR | Haute | Haute | % collectors migrés ; temps moyen ajout nouveau collector |
| 2 | Fallback & résilience incomplets / non cartographiés | Fallback partiels (certaines métriques sans secours) et pas de vue globale | Perte de données silencieuse | Moyenne-Haute | Élevée | Tableau mapping fallback ; taux d'activation breaker |
| 3 | Traçabilité documentaire insuffisante | CHANGELOG en retard, absence matrice exigences→implémentation | Difficulté audit & onboarding | Haute | Moyenne | Mise à jour CHANGELOG ; existence matrice ; delta features non documentées |

## Top 3 Quick Wins
| # | Quick Win | Action concrète | Effort estimé | Valeur | Mesure de complétion |
|---|-----------|-----------------|--------------|--------|----------------------|
| 1 | Mise à jour CHANGELOG | Ajouter section Resilience & Observability (breaker, metrics, Parquet, stratégie couverture) | ~15 min | Haute (crédibilité) | Nouveau tag daté + PR fusionnée |
| 2 | Squelette `base_collector` | Créer classe abstraite + migrer 1 collector (defillama) | 1–2 h | Haute (réduction dette) | Collector migré + tests passent |
| 3 | Matrice exigences initiale | Créer fichier requirements_matrix.md (colonnes définies) | 45 min | Haute (cadre audit) | Fichier versionné + colonnes remplies à 30% après Phase C |

## Recommandations Immédiates
1. Figer ce document (commit) avant toute exécution pour tracer l'état initial.
2. Créer / compléter `requirements_matrix.md` (squelette ajouté dans ce run).
3. Lors des runs contrôlés : journaliser timestamps d'exécution, events breaker, succès/erreurs API, taille des exports.

## Prochaines Étapes (Phases C/D)
- Run contrôlé pipeline (cycle unique) → capturer logs + métriques.
- Run court WebSocket Bybit avec coupure simulée → vérifier reprise.
- Extraction schéma SQLite + statistiques tables.
- Remplissage incrémental de la matrice.

## Notes
Ce document ne modifie pas la logique applicative : purement analytique et traçabilité audit.

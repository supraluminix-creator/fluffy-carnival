# Contribuer à ce projet

Merci de votre intérêt ! Ce guide résume les exigences techniques et la qualité attendue.

## 1. Pré-requis
- Python 3.12
- `pip install -r requirements.txt`
- Activer l'environnement virtuel avant toute commande (`.venv` recommandé)

## 2. Qualité & CI
La CI (GitHub Actions) exécute les jobs suivants:
1. `lint-and-type`: Ruff (lint), mypy (strict + strict_optional) – échec si erreurs.
2. `security`: `pip-audit` (bloquant sur vulnérabilités)
3. `bandit`: Analyse statique sécurité (échec si findings medium/high)
4. `tests`: Pytest + couverture (XML publié). Seuils progressifs: 40% (atteint), 55% (atteint), prochain palier 70% puis 75% et 80%.
5. `summary`: Résumé final.

## 3. Typage
- Mypy strict (`strict_optional=true`, `no_implicit_optional=true`).
- Ajouter des `TypedDict` / `Protocol` pour structurer les retours de collectors.
- Interdiction d'introduire `# type: ignore` sauf cas exceptionnel et documenté avec justification.

## 4. Tests
- Ajouter des tests pour toute nouvelle fonctionnalité (collector, orchestration, transformation).
- Préférer des tests rapides et hermétiques (cache nettoyé via fixture `clear_global_caches`).
- Pour les appels réseau : simuler via monkeypatch ou `pytest-httpx`.

## 5. Métriques & Observabilité
- Toute nouvelle logique d'exécution (orchestrateur, scheduler, collector) doit exposer au minimum des compteurs de succès/erreur + latence (Histogram ou Summary).
- Tests d'idempotence et stress: s'assurer de ne pas sur-compter les métriques.

## 6. Sécurité
- `pip-audit` doit rester vert.
- `bandit` ne doit signaler aucune vulnérabilité MEDIUM/HIGH.
- Éviter toute construction dynamique dangereuse (`eval`, `exec`).

## 7. Style
- Ruff fait foi (pas de flake8 isolé).
- Largeur de ligne: 120.
- Chaînes: guillemets doubles par défaut.

## 8. Commits & PR
- Branches: `feature/<slug>` ou `fix/<slug>`.
- Messages de commit concis orientés action (ex: "feat(orchestrator): add latency histogram").
- PR: description claire + checklist (tests ajoutés, types propres, pas d'ignore injustifié).

## 9. Snapshot API & Schéma
- `scripts/snapshot_runtime.py` génère `exports/runtime_snapshot.json` pour inspection rapide.
- (Optionnel) Un schéma figé `schema/runtime_snapshot.json` pourra être ajouté — garder backward compat.

## 10. Roadmap Qualité (prochaine phase)
| Palier | État | Actions principales |
|--------|------|--------------------|
| 55% | Atteint | Orchestrateur instrumenté + tests reporter élargis |
| 70% | À venir | Quick wins + timeout global orchestrator + technical_indicators |
| 75% | Planifié | Mocks WebSocket & liquidations (collectors réseau) |
| 80% | Cible | Finition + exclusions ciblées |

Tactiques:
1. Prioriser les modules à 0% (technical_indicators, base_collector, logging_config, protocols) pour gains rapides.
2. Introduire un harness de test WebSocket mock (patch `websockets.connect`).
3. Simuler scénarios API (liquidations) via monkeypatch http client.
4. Couvrir timeout global orchestrator pour lignes manquantes.
5. Ajouter tests de robustesse scheduler (replanification, suppression, erreurs job).

Exclusions possibles (justifier si appliqué):
- Branches purement défensives jamais atteintes sans manipulations réseau hasardeuses.
- Initialisation simple de logging.

Commande diagnostic couverture détaillée:
```powershell
pytest --cov-report=term-missing:skip-covered -q
```

Ne pas ajouter d'exclusion sans justification dans la PR.

## 11. Questions
Ouvrez une issue avec le tag `question` si doute; sinon discutez en PR.

Bon codage !

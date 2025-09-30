## Objet

Remodelage prod-safe: isoler le core collecte/WS/ingestion/ETL et archiver le non-core.

### Checklist livrables
- [ ] Script d’archivage fonctionnel (`tools/archive_repo.py`) — scan, move, zip, rapport
- [ ] Rapport d’archivage committé (scan + report)
- [ ] CLI core minimal (`cli_core.py`) — modes mock et public-only (+ option dérivés)
- [ ] Dépendances minimales épinglées (`requirements-core-min.txt`)
- [ ] `secrets.example.env` sans secrets réels
- [ ] Exemples d’outputs (CSV/JSON) générés
- [ ] README mis à jour (installation / run / archivage)
- [ ] Tests/unitaires basiques OK (au moins 1 test rapide)

### Rapports d’archivage
- Dossier: `archive-<timestamp>/`
- Fichiers: `scan_<timestamp>.md`, `ARCHIVE_REPORT_<timestamp>.md`

### Notes
- Toute action destructive évitée: déplacements réversibles (dossier d’archive + zip)
- Secrets: placeholders uniquement; exécuter `python tools/secret_scan.py --fail-on-find` si applicable

### Suivi
- [ ] CI (à compléter si nécessaire): lint, tests rapides, scan secrets
## Objet

Décrire brièvement le changement.

## Type de changement
- [ ] Bug fix
- [ ] Nouvelle fonctionnalité
- [ ] Refactor
- [ ] Sécurité
- [ ] Documentation

## Checklist Qualité
- [ ] Tests ajoutés / mis à jour
- [ ] Couverture maintenue (> seuil)
- [ ] Pas de secrets ajoutés (vérifié gitleaks + pre-commit)
- [ ] Lint & mypy OK localement
- [ ] Changements breaking communiqués

## Sécurité
- Surface modifiée (modules / endpoints):
- Données sensibles impactées: OUI / NON
- Risque d'escalade ou injection: OUI / NON
- Journaux (logs) contiennent potentiellement de nouvelles données sensibles ? OUI / NON

## Observabilité
- [ ] Logs structurés (event clair)
- [ ] Metrics ajoutées / ajustées (si pertinent)

## Notes de déploiement
Instructions spéciales si nécessaire.

## Liens
Issues associées / Documentation.
## Summary

- What does this PR change and why?

## Changes

- [ ] Code changes (what files)
- [ ] Tests added/updated
- [ ] Docs updated (README/CHANGELOG)

## How to test

- Steps to reproduce and validate locally

## Risk and rollback

- Risk level: Low/Medium/High
- Rollback plan: feature flag or revert commit

## Screenshots / Logs

- Optional evidence

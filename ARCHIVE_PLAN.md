# Plan d’archivage (non-core)

Objectif: réduire le dépôt à un noyau prod-safe minimal (collecte/ETL), et archiver tout le reste.

## Cible à archiver
- UI/Streamlit (`streamlit_app.py`, assets UI, notebooks, dashboards)
- Scripts PowerShell superflus / intégrations lourdes
- Tests lourds ou dépendant d’APIs externes instables
- Dossiers annexes obsolètes

## Méthode
1. Lister les chemins non-core et créer un ZIP daté (ex: `backup_fluffy_carnival_nested.zip`).
2. Déplacer les fichiers/dossiers dans `archived/` et ajouter une note par item (raison, date, commit).
3. Mettre à jour le README pour pointer vers `archived/`.

## Statut
- Workflows actifs réduits au seul fichier `.github/workflows/ci.yml` (lint + tests)
- Anciennes templates GitHub supprimées (`archived/.github/` retiré)
- Docs non-core déplacées vers `archived/docs/`
- À faire: exécution du script d’archivage automatisé (voir `tools/archive_non_core.py`).

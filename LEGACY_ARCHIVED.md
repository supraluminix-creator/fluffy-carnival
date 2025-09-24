# Legacy Code Archive

Le répertoire `fluffy-carnival/` est conservé uniquement comme archive technique (état antérieur du projet).

Statut:
- Non chargé par mypy (exclusion pyproject.toml)
- Non visé par nouvelles migrations/tests
- Sert de référence ponctuelle durant la transition

Actions prévues:
1. Suppression progressive des doublons déjà migrés.
2. Extraction de tout code utile restant vers `pipeline/` ou `tools/`.
3. Suppression finale après deux cycles de release stables.

Merci de ne PAS ajouter de nouveau code dans ce répertoire.

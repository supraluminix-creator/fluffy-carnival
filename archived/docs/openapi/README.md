# OpenAPI (Préparation)

Ce dossier prépare l'introduction d'une future API REST (exposition des collectors et métriques).

## Objectifs
- Standardiser les réponses des collectors.
- Préparer un schéma OpenAPI pour documentation et génération de clients.
- Supporter une route `/health` et `/metrics` (déjà partiellement présent côté scheduler) plus un `/collectors/snapshot`.

## Étapes proposées
1. Définir un modèle commun `CollectorEnvelope` (status, timestamp, payload).
2. Créer un module `api/app.py` (FastAPI ou Starlette) minimal.
3. Implémenter endpoints de lecture sans mutation:
   - `GET /collectors` liste des collectors disponibles.
   - `GET /collectors/run?names=...` exécution ponctuelle.
   - `GET /snapshot` export agrégé (équivalent CSV actuel mais JSON).
4. Brancher Prometheus via middleware ou exposer `/metrics` (déjà géré si start_http_server).
5. Générer openapi.json automatiquement et le versionner (optionnel).

## Décisions en attente
- Auth (API Key ou aucune pour usage interne ?)
- Pagination / filtrage (pas nécessaire au MVP)
- Formats alternatifs (CSV direct vs JSON)

## Schéma initial (brouillon)
Voir `schema-draft.yaml`.

# Run Contrôlé - Cycle Unique (Préliminaire)

Objectif: Exécuter une seule collecte legacy (`run_legacy_collection`) pour capturer un snapshot initial avant scheduler continu.

Méthode:
- Appel direct à `run_legacy_collection()` depuis script ad-hoc.
- Variables d'environnement par défaut (pas de clés sensibles ajoutées ici).
- Artefacts attendus: `exports/latest_export.csv` + `exports/pipeline_export_<timestamp>.csv` + logs structurés.

Après exécution on consignera:
- Nombre d'enregistrements collectés
- Types de métriques
- Durée du cycle
- Erreurs éventuelles


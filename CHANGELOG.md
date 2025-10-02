# 📜 CHANGELOG — new_crypto_prodsafe

## [0.1.0] - 2025-10-01
- Noyau prod-safe isolé (collecte/WS/ingestion/ETL) et outillage d’archivage (scan → exec → zip → rapports)
- Politique exemples: conserver ceux pertinents à la prod; archiver les générateurs non-core
- CI allégée et fiable (Ruff, Pytest, scans sécurité ciblés); scripts de smoke pour API/health
- Passe mypy légère (suppression d’ignore inutiles, annotations simples sur chemins critiques)
- Option export Parquet (pyarrow), lazy import et tests de latence/échec parquet
- Docs et scripts outils (secret_scan, benchmark collectors, prompts, logs summary)

## 2025-09-15
- Initialisation du projet, arborescence modulaire
- Migration du reporting PowerShell-friendly (reporter.py)
- Export CSV consolidé et horodaté (exporter.py)
- Création de tous les collectors manquants (SOPR, Bybit WS, Defillama, etc.)
- Intégration et validation par tests unitaires
- Ajout CI/CD GitHub Actions
- Documentation complète générée

## 2025-09-16
- Ajout tests unitaires pour chaque collector
- Correction des imports PYTHONPATH pour compatibilité workspace multi-projets
- Optimisation du main.py pour validation rapide de chaque module

## 2025-09-17
- Génération du diagramme technique (architecture, modules, flux)
- Analyse approfondie du code, dépendances, points d’optimisation
- Requirements.txt adapté et validé

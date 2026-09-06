# Threat Model (Version initiale)

## Portée
Pipeline de collecte crypto + agrégations SQLite locale + exports CSV + exposition métriques Prometheus.

## Actifs critiques
| Actif | Description | Impact compromission |
|-------|-------------|----------------------|
| Clés API exchange | Authentification données privées ou limites élevées | Vol, abus quotas, fraude. |
| Base SQLite (défaut `data/crypto.db`, override `CRYPTO_DB_PATH`) | Données historiques + agrégats | Perte d'historique, altération analyses. |
| Exports CSV | Source downstream (reporting / risk) | Décisions basées sur données falsifiées. |
| Code pipeline | Logique collecte & fallback | Injection comportement malveillant. |

## Principales surfaces d'attaque
1. Dépendances Python (supply chain) → SBOM + pinned versions.
2. Endpoints HTTP externes (fournisseurs) → données inattendues / rate limit abuse.
3. Fichiers locaux (SQLite/exports) → corruption disque / accès non autorisé.
4. Secrets environnement → exfiltration via logs ou exceptions.
5. Mécanismes de retry/breaker → déni de service en cas de boucle mal contrôlée.

## Menaces clés / Mesures
| Menace | Vecteur | Mesures actuelles | Gaps / Actions futures |
|--------|---------|-------------------|------------------------|
| Dépendance compromise | PyPI typosquatting | Versions épinglées, SBOM, audit futur | Intégrer scanner vuln (osv, trivy). |
| Exfiltration secrets | Logs / exceptions brutes | Masquage structlog (clés sensibles) | Ajouter scan pré-commit secrets. |
| Corruption DB | Crash pendant write | WAL + transactions | Backups périodiques (à ajouter). |
| DoS fournisseur | Rate limit | Retries budgétés + breaker 429 léger | Breaker multi-erreurs (5xx burst). |
| Données incohérentes | Schéma upstream change | Taxonomie d'erreurs + metrics schema | Alerting ratio schema errors. |
| Fragmentation / bloat | Ecritures + deletes | Vacuum conditionnel (ratio) | Archivage externe longue durée. |

## Hypothèses
- Environnement d'exécution contrôlé (pas multi-tenant hostile).
- Accès filesystem restreint (lecture/écriture locale uniquement par le process). 
- Pas d'exigence chiffrage-at-rest initial (peut être ajouté avec sqlcipher si besoin).

## Priorités d'amélioration (ordre)
1. Intégrer scanner vulnérabilités (CI) sur SBOM.
2. Ajouter backup incrémental DB + rotation (timestamped snapshots). 
3. Secrets: outil détection pré-commit + rotation documentée. 
4. Hardening: exécution utilisateur non privilégié + permissions répertoire data restrictives.
5. Signature des releases (git tag signé) + provenance supply chain.

## Événements à journaliser (min)
| Événement | Raison |
|-----------|--------|
| Ouverture/fermeture breaker | Diagnostic stabilité fournisseurs |
| Échec flush / purge / vacuum | Santé pipeline / backlog |
| Erreurs classifiées (network/rate_limit/...) | Alerte ciblée |
| Changements schéma DB (futur) | Traçabilité compatibilité exports |

## Roadmap threat modelling
- Raffiner modèle STRIDE par composant (collectors, storage, exporters).
- Mapper métriques existantes → scenarios MITRE ATT&CK pertinents (supply chain, exfiltration).
- Intégrer revues périodiques (trimestrielles) avec delta des dépendances.

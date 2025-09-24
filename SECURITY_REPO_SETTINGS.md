# Recommandations Paramètres GitHub

## Protection de branches
- main:
  - Require pull request reviews: 1+ (idéal 2 si effectif >1 mainteneur)
  - Dismiss stale approvals on new commits
  - Require status checks to pass (CI jobs: lint-and-type, tests, security, bandit, codeql, gitleaks)
  - Require branches to be up to date (optionnel selon vitesse merges)
  - Require signed commits (si workflow dev adapté)
  - Lock force-push, interdire deletions

## Policies de sécurité
- Activer GitHub Advanced Security (si licence): Code scanning (CodeQL) + Secret scanning + Dependabot alerts.
- Activer secret scanning push protection (empêche commit de patterns connus).

## Permissions Actions
- Actions workflow permissions: Read-only par défaut; élever (contents: write) uniquement par workflow si release.
- Restreindre déclenchement des workflows aux branches de confiance.

## Dependabot
- Activer alertes + security updates automatiques.
- Surveiller weekly PR backlog (<5 ouvertes) ; merger rapidement patch de sécurité.

## Secret Management
- Aucun secret dans variables par défaut de repository; utiliser seulement GitHub Secrets (ou OIDC + cloud secret manager).
- Rotation trimestrielle documentée (`SECURITY_SECRETS.md`).

## Audit Logs (si organisation)
- Revoir périodiquement: évènements de modification des protections de branches, création/suppression de secrets.

## Releases
- Ajouter génération SBOM (CycloneDX) future (job distinct) & attestation provenance (SLSA) si distribution binaire envisagée.

## Issue & PR Hygiene
- Label `security` appliqué automatiquement via template pour vulnérabilités.
- Interdire mention de PoC exploit détaillé dans issue publique (voir `SECURITY.md`).

## Automations supplémentaires (proposées)
- Semgrep workflow (SAST complémentaire) sur PR → label `sast`.
- Workflow Trivy si images Docker ajoutées plus tard.

## Table Résumé
| Domaine | État actuel | Action recommandée |
|---------|-------------|--------------------|
| Branch protection | À configurer | Appliquer règles ci-dessus |
| CodeQL | Ajouté | Surveiller alertes | 
| Secret scanning | Partiel (gitleaks) | Activer natif + push protection |
| Dependabot | Ajouté | Surveiller PR weekly |
| CODEOWNERS | Ajouté | Activer “Require review from Code Owners” |
| SECURITY.md | Ajouté | Réviser annuellement |
| Gitleaks | Ajouté | Ajouter config fine (.gitleaks.toml) |
| PR Template | Ajouté | Appliquer discipline revue |

---
Dernière mise à jour automatisée.

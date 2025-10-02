# Politique de Sécurité

## Portée
Ce document couvre le code présent dans ce dépôt (pipeline, collectors, scheduler, API) et les workflows GitHub associés.

## Signalement de vulnérabilité
Merci d'envoyer un rapport privé (pas d'issue publique) :
- Objet: [SECURITY] Description courte
- Contenu: étapes de reproduction, impact, version/commit, POC minimal

Canal recommandé: GitHub Security Advisories (Draft) ou email mainteneur (si communiqué en privé).

## SLA indicatif
| Sévérité | Exemple | Délai réponse initiale | Délai correctif visé |
|----------|---------|------------------------|----------------------|
| Critique | RCE, exfiltration secrets runtime | <24h | <7j |
| Haute | Injection, escalade privilèges locale | <48h | <14j |
| Moyenne | DoS non trivial, fuite métadonnées | <5j | <30j |
| Basse | Informationnelle / faible impact | <7j | Prochaine release |

## Bonnes pratiques actuelles
- CI: lint, type checking, tests, couverture, pip-audit, bandit, CodeQL, gitleaks.
- Logging structuré (run_id) + séparation config.
- Secrets: `.env.example` + placeholders, scan heuristique + hook pre-commit + gitleaks.
- Dépendances: dependabot hebdomadaire (pip & actions).

## Atténuations futures planifiées
- Intégration SAST additionnel (semgrep) (backlog)
- Signature des images/container si packaging (not planned yet)
- SBOM génération (cyclonedx) future

## Politique de dépendances
- Mises à jour de sécurité priorisées.
- PR dependabot doivent passer tests + audit avant merge.

## Gestion des secrets
Voir `SECURITY_SECRETS.md` pour la procédure de rotation.

## Branch Protection Recommandée
- `main`: require PR + 1 review + CI verte + code scanning.
- Interdire pushes directs (sauf mainteneurs en urgence).

## Divulgation Responsable
Ne publier aucun détail exploit tant qu'un correctif n'est pas disponible. Crédit accordé dans CHANGELOG si souhaité.

Merci de contribuer à la sécurité du projet.

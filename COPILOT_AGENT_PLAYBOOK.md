# Copilot Agent Playbook

But: standardiser l'utilisation d'un agent Copilot (ou similaire) pour aider le développement et l'audit du dépôt `new_crypto_prodsafe`.

Règles générales
- Ne jamais commuter de secrets (clés API, certificats privés, mots de passe) dans le dépôt. Utiliser `secrets.*` dans GitHub Actions et ajouter les variables d'environnement locales dans `.env` (ex: `.env.local`) qui sont ignorés par git.
- Avant tout commit majeur, lancer le test complet (`.venv\Scripts\python.exe -m pytest -q`) et le linter (`ruff .`) localement.
- Si l'agent automatise des commits, ajouter un message clair `chore(agent): ...` et référencer le prompt source.

Checklist pour l'agent
1. Contexte
   - Branch active
   - Objectif de la tâche
   - Tests existants et couverture
2. Sécurité
   - Scanner les fichiers de configuration (workspace, .env.example, CI) pour des clés en clair
   - Ne modifier que les fichiers nécessaires
3. Modifications de CI
   - Remplacer les valeurs sensibles par `secrets.*`
   - Ajouter une étape de détection de secrets (grep/bandit/pip-audit)
4. Tests
   - Lancer pytest et vérifier qu'il n'y a pas de régressions
5. Commit & PR
   - Un commit = une intention. Message format: `type(scope): courte description` (ex: `chore(ci): use secrets for API_WRITE_KEY`)
   - Ajouter un descriptif dans la PR: ce que change, pourquoi et comment tester localement

Bonnes pratiques pour prompts
- Spécifier le repository racine et la branche
- Donner le résultat attendu (tests verts, CI passe)
- Exiger un contrôle anti-secret avant commit

Exemples de tâches
- "Replace hardcoded secrets in CI by GitHub secrets and add a grep-based pre-check step"
- "Add tests for rate limiting and confirm via pytest"

Notes
- Ce playbook est intentionnellement léger. Pour des audits plus stricts, intégrer `detect-secrets` (Yelp) ou `truffleHog` dans la CI.

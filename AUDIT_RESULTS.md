# Audit technique — Crypto Monitor (fluffy-carnival)

Date: 2025-09-29

## Résumé exécutif

1) Endpoints externes et robustesse HTTP
- Plusieurs implémentations HTTP coexistent (pipeline/http.py, http_client.py, http_wrappers.py) avec duplication de responsabilités et comportements incohérents (retries, timeouts, backoff). Regrouper en un seul module et appliquer des timeouts + retries idempotents par défaut.

2) Collectors hétérogènes et fallback
- Des collectors appellent des endpoints historiques/devenus 404. L’exemple MVRV a été corrigé vers bitcoin-data.com/api/v1. Généraliser une politique claire de fallback, logs structurés et cache disque pour limiter quotas.

3) Sécurité et clés
- Pas de clés en clair dans le code (ok). S’assurer que toutes les intégrations lisent les variables d’environnement, valider l’absence d’output de secrets dans les logs, ajouter un script de scan secrets (présent: tools/secret_scan.py) au CI.

4) Observabilité et erreurs
- Logging présent (structlog) mais pas homogène. Uniformiser le logger (format, champs) et remonter les erreurs réseau avec contexte; exposer /health et métriques déjà en place, c’est bien.

5) IA: usages manuels recommandés
- Pour limiter les coûts/quotas, privilégier un flux manuel: génération de prompts Markdown + bookmarklets/UI helper. Fallback AI ajouté (Ollama → OpenRouter → HuggingFace) sécurisé par env vars.

6) Dette structurelle
- Modules redondants et noms proches (base_collector vs collectors/base_collector.py, http*, llm*). Proposer un plan de consolidation minimal sans casser l’existant.

## Détails par thème

### HTTP & Réseau
- Duplication: pipeline/http.py, http_client.py, http_wrappers.py, fallbacks.py. Risque d’incohérence de headers, proxies, retries.
- Quick win: définir une fabrique httpx.AsyncClient unique, gérer verify SSL, follow_redirects, backoff (ex: 100ms, 400ms, 1.6s).

### Collectors
- MVRV: anciens endpoints (charts/api.bgeometrics.com) génèrent 404/301. Le collector MVRV a été refondu pour utiliser d’abord bitcoin-data.com/api/v1, puis fallbacks. Parser robuste (mvrvZscore, unixTs, d) et cache.
- D’autres collectors (onchain/sentiment) doivent être revus selon la même grille: endpoints vivants, schémas de réponse variés, retries/backoff, caches.

### Sécurité
- Clés via env (OK). Ajouter masque de champs sensibles dans logs. Vérifier qu’aucune clé n’est stockée en BDD/export. Documenter la rotation et l’override local (.env.local).

### Observabilité
- /health et métriques Prometheus OK. Ajouter compteurs d’échecs réseau par host, latence p95/p99.

### IA & Prompts
- Ajout d’un adapter AI multi-fournisseurs avec fallback (integrations/ai_provider.py) et d’un générateur de prompts Markdown (prompts/generator.py). Recommandation: flux manuel (bookmarklets + UI helper) pour préserver quotas.

### Tests & CI
- Tests unitaires à étendre. Ajout de tests ciblés pour le générateur de prompts et le client IA. CI minimal ajouté (pytest ciblé). Étendre ensuite au reste du repo, ajouter secret scan.

## Recommandations priorisées

1) Unifier la couche HTTP (1 jour)
- Créer pipeline/net/http_client.py unique; migrer progressivement les appels; activer retries/backoff; métriques latence/erreurs par host.

2) Normaliser les collectors critiques (1–2 jours)
- Appliquer la même stratégie que MVRV: endpoints ordonnés + parser flexible + cache; ajouter tests avec payloads figés.

3) Flux IA manuel par défaut (0.5 jour)
- Utiliser prompts/generator.py, tools/prompt-launcher.html; implémenter bookmarklets simples.

4) Sécurité (0.5 jour)
- Masquer secrets dans logs, valider absence de secrets en BDD/export; documenter rotation.

5) Étendre CI (1 jour)
- Ajouter lint (flake8/black/isort), mypy, pytest sur suites unitaires; intégrer tools/secret_scan.py; artefacts coverage.

## Risques & mitigations
- Rate-limit externes: cache disque + espacements + retries backoff.
- Changement de schéma API: parsers tolérants, feature flags, procédure de rollback documentée.
- Endpoints morts: centraliser la configuration et vérifier dans le CI via tests «probe» hors réseau (mocks).

---

Annexes: détails des fichiers nouveaux/modifiés dans cette PR, revue des endpoints BGeometrics/bitcoin-data.com, et plan d’évolution.

# 🛣️ ROADMAP — new_crypto_prodsafe

Cette roadmap classe les priorités d’évolution du projet par ordre d’importance et fournit un **prompt dédié à GitHub Copilot** pour guider l’implémentation.

---

## 🔴 Phase 1 (Immédiat — Production)
1. **Performance (httpx + async)**  
   - Remplacer `aiohttp` par `httpx.AsyncClient`.  
   - Paralléliser les appels API critiques.  

2. **Retry/Backoff**  
   - Généraliser backoff exponentiel (lib `tenacity` ou wrapper maison).  

3. **Cache (disk/mémoire)**  
   - Ajouter cache TTL (diskcache, SQLite, ou Redis).  

---

## 🟠 Phase 2 (Stabilisation & Observabilité)
4. **Metrics Prometheus + logs structurés**  
   - Exporter métriques runtime (latence, erreurs, succès).  
   - Logs JSON avec `structlog`.  

5. **Type hints (mypy/pylance)**  
   - Renforcer les annotations partout.  
   - Activer `mypy` dans CI/CD.  

---

## 🟡 Phase 3 (Qualité & Discipline Dev)
6. **Lint/Format CI/CD**  
   - Ajouter workflow GitHub Actions : ruff + black + isort.  

7. **Docstrings**  
   - Compléter doc inline (style Google/NumPy).  

---

## 🟢 Phase 4 (Avancé — Scalabilité)
8. **Tests avancés**  
   - Tests d’intégration avec mocks (httpx/respx).  
   - Tests de charge (1000 métriques/min).  
   - Tests de résilience (pannes API simulées).  

9. **Database ORM léger**  
   - SQLModel ou Tortoise pour multi-DB et migrations avancées.  

---

# 🤖 Prompt GitHub Copilot — Implémentation Roadmap

## Contexte
Projet : `new_crypto_prodsafe`  
But : refactor du MONOLITH robuste → pipeline modulaire prod-safe.  
Contrainte : appliquer la roadmap en respectant **méthodologie prod-safe** (analyse → solution complète → delta explicatif).  

## Mission
Copilot doit :  
1. Lire la roadmap.  
2. Implémenter les features dans l’ordre (Phase 1 → Phase 4).  
3. Toujours produire :  
   - Code complet prod-safe.  
   - Tests unitaires.  
   - Commit message clair.  
   - Delta explicatif.  

## Étapes guidées
- Phase 1 → remplacer aiohttp par httpx.AsyncClient, ajouter retry/backoff, cache TTL.  
- Phase 2 → exporter métriques Prometheus/logs structurés, renforcer type hints.  
- Phase 3 → CI/CD lint (ruff, black, isort), docstrings.  
- Phase 4 → tests avancés (intégration, charge, résilience), ORM optionnel.  

## Exigences
- Respect du schéma normalisé : `timestamp, asset, metric_name, value, source, confidence_score`.  
- Async/await pour tous les collectors.  
- Pytest pour tous les tests.  
- CI/CD GitHub Actions pour valider lint + tests.  

---

⚠️ Règle d’or : ne jamais livrer un patch minimal, toujours livrer **code complet + tests + explication delta**.


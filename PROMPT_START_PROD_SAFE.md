# ▶️ Lancement immédiat — Sprint 1 (Prod-Safe)  
**Contexte** : feu vert opérationnel. Tu es dev Python senior, tu prends la main sur la refactorisation prod-safe du repo `crypto_pipeline_core`.  
Méthodologie obligatoire : **Toujours** → Analyse complète → Solution complète → Delta clair. Refactoriser par phases, PR courtes, tests et feature flags.

⚠️ Rappel : Pour toute la partie **timings, quotas, rôles Main/Backup**, tu dois **t’appuyer strictement sur le fichier `COPILOT_COLLECTORS_OPTIMISATION.md`** déjà présent dans le repo.  
Ce document est la **source unique de vérité** pour la fréquence de collecte et la hiérarchie des APIs.

---

## 🎯 Objectifs prioritaires (Sprint 1 – Stabilisation, à exécuter **immédiatement**)
1. Fallback généralisé (Main → Backup, selon `COPILOT_COLLECTORS_OPTIMISATION.md`)
2. Retry + backoff centralisé (décorateur / base_collector)
3. Scheduler granulaire (5/15/30/60/6h, **respect strict du fichier `COPILOT_COLLECTORS_OPTIMISATION.md`**)
4. structlog + Prometheus uniformisés (metrics globales)
5. Mise en place de PRs petites & prod-safe (feature flags, rollback)

---

## 🧩 Workflow d’exécution (règles générales)
- **Branches** : `feature/<ticket>-<short>` (ex: `feature/fallback-coin-gecko`)  
- **Commits** : Conventional Commits (`feat:`, `fix:`, `chore:`).  
- **PR** : petite (max 200-300 lignes), description : `Contexte`, `Changements`, `Tests`, `Delta`, `Rollback plan`.  
- **Tests** : toute PR doit inclure tests unitaires/async (pytest + pytest-asyncio).  
- **Secrets** : jamais en clair, utiliser GitHub Secrets / .env local ignoré par git.  
- **Coverage** : visée ≥ 80% pour code modifié (graduel).

---

## 📁 Fichiers / modules à ajouter ou modifier (concret)
- `core/base_collector.py` ← **création obligatoire** (héritage commun)
- `collectors/*` ← refactoriser pour hériter de `BaseCollector` et appliquer fallback (selon `COPILOT_COLLECTORS_OPTIMISATION.md`)
- `scheduler/runner.py` ← scheduler granulaire, **aligné avec les timings du fichier `COPILOT_COLLECTORS_OPTIMISATION.md`**
- `observability/logging_config.py` ← structlog config
- `observability/metrics.py` ← Prometheus metrics & helpers
- `tests/` ← tests unitaires & mocks pour chaque collector
- `.github/workflows/ci.yml` ← garantir lint/mypy/pytest/coverage steps

---

## ✅ Critères d’acceptation globaux Sprint 1
- Tous les collectors appliquent fallback (Main → Backup) **conformément à `COPILOT_COLLECTORS_OPTIMISATION.md`**.
- Retry/backoff logic centralisé et testé.
- Scheduler granulaire tourne aux bons intervalles (5/15/30/60/6h) **exactement selon `COPILOT_COLLECTORS_OPTIMISATION.md`**.
- structlog output standardisé ; Prometheus metrics publiées.
- Tests ajoutés pour chaque collector modifié ; CI passe.
- PRs documentées avec Analyse → Solution → Delta ; rollback plan fourni.

---

## 📣 Actions à lancer **maintenant**
- [ ] Créer la branche `feature/fallback-base-collector`.
- [ ] Implémenter `base_collector.py` + refactor CoinGecko collector avec fallback vers CMC (conformité `COPILOT_COLLECTORS_OPTIMISATION.md`).
- [ ] Ajouter tests avec mocks API.
- [ ] Ouvrir PR avec checklist complète.
- [ ] Après merge, enchaîner sur retry/backoff, scheduler, observability.

---

## 🔒 Rappel sécurité & prod-safe
- Ne jamais committer d’API keys. Utiliser GitHub Secrets.  
- Feature flags pour toggler les nouveaux collectors (`FEATURE_FALLBACK_ENABLED=true`).  
- Toutes les étapes doivent être testées sur `develop` avant `main`.  
- Documenter le rollback (git revert / tag prior release).

---

## ✅ Résumé final
Tu as le feu vert pour lancer Sprint 1.  
Commence par **fallback + base_collector + tests**, en respectant **strictement les timings et quotas décrits dans `COPILOT_COLLECTORS_OPTIMISATION.md`**.  
Chaque PR doit être courte, testée, documentée et prod-safe.

# 📝 Prompt – Roadmap & TODO (Prod-Safe)

## 📊 État actuel du projet (audit)
- ✅ **Déjà en place** : scheduler asyncio (mais non granulaire), structlog partiel, retry/backoff partiel, export CSV stable.
- 🟡 **Partiellement en place** : fallback (CoinGecko → CMC seulement), Prometheus (certains collectors), docstrings minimales.
- ❌ **Pas en place** : tests unitaires (mocks API), CI/CD complet, factorisation (`base_collector.py`), stockage alternatif (SQLite/Parquet), exports dashboards, release tagging, collectors avancés.

---

## 🎯 Priorités (socle à fiabiliser)
1. **Fallback généralisé** : chaque collector doit avoir un backup (ex. CoinGecko → CMC, Bybit → Binance).
2. **Retry/backoff systématique** : étendre à tous les collectors.
3. **Scheduler granulaire** : orchestrer selon le timing défini :
   - 5 min : macro, on-chain, dérivés
   - 15–30 min : DeFi, stablecoins
   - 1h : sentiment, TokenMetrics
   - 6h : historiques lourds
4. **structlog + Prometheus généralisés** : logs structurés + métriques uniformisées.
5. **Tests unitaires avec mocks API** : pytest obligatoire (gestion d’erreurs, fallback, quotas).
6. **Factorisation** : `base_collector.py` pour centraliser retry, cache, logging.
7. **CI/CD complet** :
   - pytest
   - lint (flake8)
   - format (black)
   - type-check (mypy)
   - sécurité (bandit, safety)
   - coverage report + badge
8. **Documentation enrichie** : README avec tableau Main/Backup + timings, docstrings Google/NumPy.

---

## 📅 Étapes secondaires (après stabilisation)
- Stockage alternatif : SQLite/Parquet en plus du CSV.
- Export connecteurs : Grafana/PowerBI.
- Release tagging + changelog auto.
- Extension collectors : TokenMetrics, signaux sentiment avancés.

---

## ✅ TODO list (Kanban style)
### Phase 1 – Stabilisation
- [ ] Implémenter fallback généralisé dans chaque collector.
- [ ] Étendre retry/backoff à tous les collectors.
- [ ] Revoir scheduler pour granularité (5/15/60 min).
- [ ] Uniformiser structlog et Prometheus.

### Phase 2 – Robustesse
- [ ] Ajouter tests pytest avec mocks API.
- [ ] Créer `base_collector.py` et refactoriser collectors existants.
- [ ] Compléter la documentation technique (README + docstrings).

### Phase 3 – Industrialisation
- [ ] Mettre en place CI/CD complet sur GitHub Actions.
- [ ] Ajouter coverage badge, lint/format/type/sécurité automatiques.
- [ ] Ajouter tagging SemVer + changelog automatisé.

### Phase 4 – Extensions
- [ ] Intégrer stockage SQLite/Parquet.
- [ ] Ajouter connecteurs Grafana/PowerBI.
- [ ] Étendre collectors (TokenMetrics, signaux avancés).

---

## 🛡️ Méthodologie Prod-Safe
- Toujours partir d’une **analyse complète** avant toute correction.
- Fournir une **solution intégrale**, pas un patch partiel.
- Documenter le **delta clair** entre l’existant et la version corrigée.
- **Refactoriser par phases**, sans casser la prod (feature flags, branches isolées).
- Garantir des **tests et métriques** avant déploiement (pytest + Prometheus).
- S’appuyer sur le **changelog et tags Git** pour rollback si besoin.

---

👉 Tâche : Merci de confirmer la faisabilité de chaque étape, d’indiquer si certains points doivent être adaptés ou non au projet dans son état actuel, puis de proposer un ordre de mise en œuvre réaliste (sprints).

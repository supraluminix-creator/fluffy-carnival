# TODO opt-in intégrations et automatisations

Objectif: garder le projet autonome et minimal par défaut, tout en offrant des intégrations optionnelles (opt‑in) activables par flags/tâches sans gonfler le cœur.

Statut rapide
- Base: façade HTTP unifiée, flags LLM/AI POST, collectors durcis, tasks VS Code (lint/types/tests), dashboards Grafana pack — OK
- À faire (opt‑in): rapports/exports conviviaux, events JSONL, Notion/Calendar, LangChain extra, Grok adapter, couverture + artefacts CI, sécurité (SBOM/gitleaks)

1) Exports & rapports locaux (offline‑first)
- [ ] Reports quotidiens Markdown sous `reports/` (KPIs clés, incidents, latences, retries)
- [ ] Exports CSV/Parquet standardisés sous `exports/` (timestampés)
- [ ] Tâche VS Code: "Reports: generate daily"
- [ ] Doc courte `README_REPORTS.md` (schémas, formats, consommation)

2) Événements locaux (journal machine‑lisible)
- [ ] Émettre des events JSONL sous `reports/events/` (start/stop, erreurs typées, seuils)
- [ ] Option HTTP local (127.0.0.1) pour webhooks si nécessaire (désactivé par défaut)

3) Notion (opt‑in SaaS, désactivé par défaut)
- [ ] Script `scripts/notion/push_summary.py` (crée/MAJ une page + ligne dans DB)
- [ ] Variables: `NOTION_API_TOKEN`, `NOTION_DATABASE_ID`
- [ ] Tâche VS Code: "Notion: push daily summary"
- [ ] Tests unitaires (mock HTTP), doc d’usage minimal

4) Notion Calendar / ICS (opt‑in, offline d’abord)
- [ ] Générer un `.ics` local avec événements clés (exécutions, incidents, maintenance)
- [ ] Tâche VS Code: "Calendar: emit .ics"
- [ ] Doc: import manuel dans Notion Calendar ou calendrier perso

5) LangChain (opt‑in, extra requis, sans toucher au core)
- [ ] Extra `langchain` (requirements optionnels)
- [ ] Wrapper LLM qui utilise la façade HTTP existante (OpenAI‑like ou Ollama)
- [ ] Notebook d’exemple: résumé hebdo à partir des exports/README/incident log

6) Grok (XAI) — adapter opt‑in recommandé
- [ ] Petit adapter `integrations/grok_adapter.py`:
  - Entrées: liste d’actifs/termes; fenêtres temporelles
  - Sorties: JSON structuré (sentiment score, top hashtags, tendances, justification)
  - Caching local (TTL), retries/backoff via façade HTTP, métriques Prometheus
  - Flags: `GROK_ENABLED=1`, `GROK_API_KEY`, `GROK_TIMEOUT`, `GROK_CACHE_TTL`
- [ ] Tâche VS Code: "Grok: refresh social sentiment"
- [ ] Tests: happy path (mock), rate‑limit (429 -> backoff), schéma variant (robustesse)
- [ ] Exposition: écrire résultats sous `exports/social/` + intégrer dans rapport Markdown si présent

7) Manus — évaluation et alternative locale
- [ ] Évaluer l’apport réel vs complexité (coût, secrets, orchestration redondante)
- [ ] Alternative locale proposée:
  - Script `scripts/auto_orchestrator.ps1` pour enchaîner: tests → collecte → exports → rapports
  - Planification via Windows Task Scheduler (offline), logs sous `run/`
- [ ] Décision: intégrer Manus plus tard seulement si besoin de multi‑agents distribués/quotas externes

8) Observabilité & CI
- [ ] Tâche VS Code: "Test (venv, coverage)" (sortie coverage.xml déjà présente)
- [ ] CI (option): upload coverage + SBOM artefacts
- [ ] Dashboards Grafana supplémentaires: writer/flush, DB santé, breaker HTTP détaillé par endpoint

9) Sécurité
- [ ] Gitleaks (déjà présent: `gitleaks.toml`) — ajouter run facile en tâche VS Code
- [ ] SBOM (pip‑license/cyclonedx) — script + artefact CI optionnel
- [ ] Documentation secrets (`SECURITY_SECRETS.md`) — compléter variables opt‑in

Critères d’acceptation généraux
- Opt‑in strict: aucune nouvelle dépendance par défaut, activation via flags/Tâches
- Tests: au moins 1 happy path + 1 edge/path d’erreur pour chaque adapter
- Observabilité: chaque adapter expose métriques minimales (latence, erreurs, taux succès)
- Docs: une page courte par intégration expliquant variables, exécution, outputs

Plan de livraison proposé
1. Quick wins: Reports Markdown + CSV/Parquet + tâches VS Code (offline)
2. Events JSONL + Calendar (.ics)
3. Grok adapter (opt‑in) + intégration au rapport
4. Notion opt‑in + LangChain extra + notebook
5. Orchestrateur local (Task Scheduler) et, plus tard, décision Manus

### 10) X API v2 (opt‑in, free tier) — watchlist réduite

- [x] Adapter `integrations/x_adapter.py` minimal pour watchlist ciblée (hashtags/comptes limités)
- [x] Script `scripts/x_refresh.py` pour écrire `exports/social/latest_x_curated.json`
- [x] Tâche VS Code: "X: refresh curated feed" (opt‑in, par défaut off)
- [x] Flags/env: `X_ENABLED=0`, `X_BEARER_TOKEN`, `X_WATCHLIST`, `X_LIMIT`, `X_TIMEOUT`, `X_CACHE_TTL`
- [ ] Tests: quotas/free tier (limitation volumétrique), robustesse schéma
- Acceptation: ne remplace pas Grok, sert d’appoint ciblé sans coût; off par défaut

Watchlist initiale proposée (compatible env):
```
X_WATCHLIST="#BTC,#ETH,#SOL,#Altcoins,#Crypto,#DeFi,#Airdrop,@binance,@cz_binance,@CoinMarketCap,@APompliano,@WatcherGuru,@AltcoinDaily,@CryptoKaleo,@WuBlockchain,@TheBlock__,@BitcoinMagazine"
```

### 11) Rumour.app (opt‑in) — en attente d’invitation/code

- [ ] Veille API/SDK public; si dispo, créer `integrations/rumour_adapter.py` sur le modèle Grok (façade HTTP + cache + export)
- [ ] Flags/env: `RUMOUR_ENABLED=0`, `RUMOUR_API_KEY` (si requis)
- [ ] Tâche VS Code: "Rumour: refresh early narratives"
- [ ] Tests: placeholder si non joignable; fallback silencieux
- Acceptation: aucune dépendance ajoutée tant qu’aucun accès; intégration quand codes/invites disponibles

Note veille: cartographier endpoints/documentation publique; évaluer faisabilité sans SDK propriétaire; définir données minimales (titre, lien, score, heure) pour export JSON.

### 12) Sentient AGI / ROMA (opt‑in) — évaluation

- [ ] Étude d’impact: dépendances et empreinte (poids, services, GPU), bénéfice vs coût
- [ ] Scénario POC: exécution locale d’un agent ROMA ciblé (market data + wallet tracking) avec export JSON (offline)
- [ ] Intégration minimale: adapter en tant que source optionnelle (scripts/roma_fetch.py), sans coupler au core
- [ ] Documentation: comment activer/désactiver, ressources nécessaires
- Acceptation: rester 100% optionnel; pas d’alourdissement du core; valeur ajoutée démontrée avant intégration plus profonde

Note POC: cibler un run court et isolé (10–15 min) avec sources locales ou gratuites; éviter tout besoin GPU/cloud payant; consigner ressources et outputs.

### 13) Whale/on-chain alerts (opt‑in, sources gratuites seulement)

- [ ] Étude des sources free/OSS activables sans coût: Whale Alert (flux public limité), Etherscan (API free tier), ClankApp/Telegram (lecture bot si autorisée), DeBank (si endpoint public), Arkham/DexCheck (probablement payants → backlog)
- [ ] Adapter(s) optionnels:
  - `integrations/etherscan_adapter.py` (si Etherscan API key): endpoints simples (wallet txs, token transfers) + cache TTL + export JSON
  - `integrations/whale_feed_adapter.py` (si source publique exploitable légalement): agrégation minimale, pas de scraping non autorisé
- [ ] Flags/env: `ETHERSCAN_ENABLED=0`, `ETHERSCAN_API_KEY=`, etc.
- [ ] Tâches VS Code: "Etherscan: refresh watch wallets", "WhaleFeed: refresh"
- [ ] Tests: mock HTTP, quotas, formats variables
- Acceptation: aucune dépendance tierce payante; respecter les CGU; garder l’analyse orientée signaux clairs (gros transferts, vers/depuis exchanges)

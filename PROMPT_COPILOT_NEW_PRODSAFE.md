# 🚀 Prompt GitHub Copilot — Reboot MONOLITH → `new_crypto_prodsafe`
*(Français — pour VS Code / Copilot @workspace — méthode prod-safe exigée)*

---

## 🎯 Contexte  
Nous ne faisons **pas une fusion** des projets.  
L’objectif est un **refactoring complet du MONOLITH** (V1 → V3) dans un **nouveau dossier `new_crypto_prodsafe/`**, afin de créer un pipeline **production-grade** qui :  

- Garde la **robustesse et la couverture fonctionnelle** du MONOLITH (reporting riche, APIs variées, fallback robustes).  
- Adopte une architecture inspirée de `crypto_pipeline_core` (modulaire, SOLID, async, normalisation).  
- Intègre les **métriques et services manquants** :  
  - SOPR (via BGeometrics / SOPR_blockchain).  
  - Service WS fiable (Bybit WebSocket, reconnect/backoff).  
- Préserve **interface utilisateur PowerShell** (reporting lisible).  
- Ajoute **export CSV consolidé** et version horodatée comme dans v15.2.  

---

## 📂 Arborescence cible (new_crypto_prodsafe/)
```
new_crypto_prodsafe/
├── .env
├── requirements.txt
├── data/
│   └── crypto.db
├── exports/
│   ├── latest_export.csv
│   ├── pipeline_export_<timestamp>.csv
├── pipeline/
│   ├── __init__.py
│   ├── base_collector.py
│   ├── normalizer.py
│   ├── reporter.py
│   ├── exporter.py
│   ├── signals.py
│   ├── collectors/
│   │   ├── coingecko.py
│   │   ├── defillama.py
│   │   ├── sopr_bgeometrics.py
│   │   ├── sopr_blockchain.py
│   │   ├── bybit.py
│   │   ├── bybit_ws.py
│   │   ├── hashrate.py
│   │   ├── txcount.py
│   │   └── altme.py
│   └── storage/
│       ├── sqlite_adapter.py
│       └── migrations.py
├── main.py
└── tests/
    ├── test_collectors.py
    ├── test_signals.py
    └── test_exporter.py
```

---

## ✅ Mission pour Copilot  
### Phase 1 — Analyse
- Comparer monolithV1.py, monolithV2.py, monolithV3.py.  
- Générer `analysis/monolith-comparison.md` listant les différences (macro, dominance, stablecoins, dérivés, signaux, sentiment, hashrate, txcount).  

### Phase 2 — Extraction
- Sélectionner et extraire le **meilleur code legacy**.  
- Conserver robustesse des fallbacks et reporting.  

### Phase 3 — Refactorisation
- Recréer le pipeline sous `new_crypto_prodsafe/` avec squelette modulaire.  
- Intégrer reporting PowerShell lisible (`tabulate` ou fallback pandas).  
- Consolider exports CSV (unique + horodaté).  

### Phase 4 — Extensions
- Ajouter modules manquants : `sopr_bgeometrics`, `sopr_blockchain`.  
- Implémenter `bybit_ws.py` robuste (reconnect/backoff).  
- Hériter des collectors manquants de v15.2 si pertinents.  

---

## 🔒 Méthodologie prod-safe  
À chaque étape :  
1. **ANALYSE** → ce qui existe, ce qui fonctionne, dépendances.  
2. **SOLUTION PROD-SAFE** → code complet, fonctionnel, prêt à exécuter.  
3. **DELTA EXPLICATIF** → commit clair, diff minimal.  

Tests :  
- Pytest minimal pour collectors, exports, reporter.  
- CI/CD GitHub Actions : installer deps, run `pytest -q`.  

---

## 📌 TODO Optimisé (Pro Python Prod-Safe)  

- [ ] **Créer nouvelle branche** `feature/new_crypto_prodsafe`.  
- [ ] **Phase 1 : Analyse**  
  - [ ] Lancer `monolithV1.py`, `monolithV2.py`, `monolithV3.py` → logs.  
  - [ ] Générer `analysis/monolith-comparison.md`.  
  - [ ] Identifier métriques/collectors critiques.  

- [ ] **Phase 2 : Extraction**  
  - [ ] Créer `pipeline/adapters/` avec le meilleur de chaque monolith.  
  - [ ] Tester insertion SQLite + export CSV.  

- [ ] **Phase 3 : Refactorisation**  
  - [ ] Implémenter `base_collector.py`, `normalizer.py`.  
  - [ ] Ajouter `reporter.py` PowerShell-friendly.  
  - [ ] Restaurer export CSV consolidé + horodaté.  
  - [ ] Couvrir tests unitaires.  

- [ ] **Phase 4 : Extensions**  
  - [ ] Créer `collectors/sopr_bgeometrics.py`.  
  - [ ] Créer `collectors/sopr_blockchain.py`.  
  - [ ] Implémenter `bybit_ws.py` robuste.  
  - [ ] Valider collectors manquants v15.2.  

- [ ] **CI/CD**  
  - [ ] Ajouter workflow GitHub Actions `ci.yml`.  
  - [ ] Lancer pytest sur chaque push/PR.  

- [ ] **Documentation**  
  - [ ] Générer `README_NEW_PRODSAFE.md`.  
  - [ ] Ajouter diagramme comparatif MONOLITH → v15.2 → new_crypto_prodsafe.  
  - [ ] Journal de version (CHANGELOG.md).  

---

## 📜 Règle d’or  
Toujours : **ANALYSE → SOLUTION PROD-SAFE (CODE COMPLET) → DELTA**.  
Ne jamais livrer un patch minimal sans préserver logging, metrics et interfaces.  

---

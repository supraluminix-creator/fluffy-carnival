# 🔧 Prompt – Intégration Bybit WS (Liquidations H24) en mode Prod-Safe

## 🎯 Contexte
Le projet **Crypto Monitor** a été refactoré et stabilisé avec une méthodologie **prod-safe** (analyse → solution complète → delta clair).  
Nous devons maintenant intégrer et fiabiliser un **service de collecte temps réel Bybit WebSocket** (liquidations BTC/ETH), tournant **H24 en arrière-plan**.

## 📝 Tâche demandée
1. **Analyse & comparaison**  
   - Récupérer le collector **`bybit_ws`** dans les deux branches historiques :  
     - `crypto_pipeline_core_v15_2`  
     - `crypto_pipeline_core`  
   - Comparer les implémentations.  
   - Choisir la version la plus robuste/pertinente comme base.  

2. **Adaptation Prod-Safe**  
   - Refactoriser pour appliquer la méthodologie déjà utilisée dans le projet :  
     - **Fallback automatique** (si WS tombe, tenter reconnect).  
     - **Retry/backoff exponentiel** (tenacity).  
     - **Logs structlog** harmonisés.  
     - **Métriques Prometheus** (latence, erreurs, volume d’events).  
     - **Tests unitaires/mocks** (simuler WS, erreurs réseau).  
     - **Documentation** claire (docstrings + README).  

3. **Intégration H24**  
   - Faire tourner le collector **séparément du runner main** (process indépendant).  
   - Scheduler adapté (Windows Task Scheduler, systemd, ou autre solution jugée plus fiable).  
   - S’assurer que le flux WS tourne en continu avec **reconnexion automatique**.  

4. **Tests & validation**  
   - Vérifier que les liquidations BTC/ETH sont bien collectées en continu.  
   - Tester les cas d’erreur (perte de connexion WS, quotas, timeouts).  
   - Vérifier intégration avec le reste du pipeline (export CSV, logs, Prometheus).  

---

## ✅ Résultat attendu
- Un module **`bybit_ws.py`** :  
  - **Robuste (prod-safe)**  
  - **Testé (unitaires + mocks)**  
  - **Observabilité complète** (logs + métriques)  
  - **Indépendant du runner main** (H24 en fond, avec auto-reconnect).  

- Intégration harmonieuse dans le projet (même architecture, mêmes standards que les autres collectors).  

---

⚡ **Instruction finale** :  
> Sois **pragmatique et minutieux**, applique **exactement le même mode opératoire que pour les autres optimisations prodsafe**.  
> Objectif = un service temps réel **Bybit WS stable H24**, industrialisable et maintenable.

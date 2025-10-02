# Gestion des Secrets & Rotation

Ce dépôt a précédemment contenu des clés API réelles dans `.env`. Le fichier est désormais assaini. Toute clé exposée dans l'historique Git doit être ROTÉE immédiatement.

## 1. Plan d'action immédiat
| Secret | Action recommandée | Délai | Notes |
|--------|--------------------|-------|-------|
| DUNE_API_KEY | Révoquer clé existante, générer une nouvelle | <24h | Limiter droits lecture uniquement | 
| COINMARKETCAP_API_KEY | Régénérer clé | <24h | Vérifier quotas | 
| ETHERSCAN_API_KEY | Régénérer | <24h | | 
| INFURA_API_KEY | Invalider projet clé, recréer projet | <24h | Restreindre aux réseaux nécessaires | 
| BINANCE_API_KEY | Désactiver ancienne, créer nouvelle en lecture seule | <24h | Activer IP allowlist | 
| BYBIT_API_KEY | Régénérer, lecture seule | <24h | IP allowlist si possible | 
| COINGECKO_API_KEY | Régénérer | <24h | | 
| BITQUERY_API_KEY | Régénérer | <24h | | 
| CRYPTOCOMPARE_API_KEY | Régénérer | <24h | | 
| TOKEN_METRICS_API_KEY | Régénérer | <24h | | 

## 2. Principes
- Jamais de secret réel dans un fichier versionné (`.env` local uniquement, ignoré par git).
- Utiliser CI/CD secrets (GitHub Actions Secrets) pour l'injection runtime.
- Principe du moindre privilège : permissions lecture si écriture non nécessaire.
- Rotation proactive: tous les 90 jours (planifier rappel calendrier / workflow GitHub).
- Journaliser (hors repo) la date de création / expiration attendue pour chaque clé.

## 3. Format `.env`
Les placeholders `REPLACE_ME` doivent être remplacés localement par un développeur mais **NE PAS** être commités. Exemple :
```
# local uniquement (jamais commit)
DUNE_API_KEY=live_xxxxxxx
```

## 4. Outils de détection
Un script `tools/secret_scan.py` fournit un scan heuristique (regex patterns) pour prévenir un commit accidentel.

## 5. Pré-commit
Ajouter le hook (voir section) pour bloquer un commit contenant une correspondance à haut risque.

## 6. Procédure de rotation générique
1. Créer nouvelle clé sur le provider.
2. Mettre à jour le secret dans le store sécurisé (GitHub, vault, variable runtime) sans supprimer l'ancienne.
3. Déployer / tester.
4. Révoquer l'ancienne clé.
5. Journaliser l'opération (hors repo) : qui, quand, clé (hash tronqué).

## 7. Nettoyage historique (optionnel)
Si le repo public ou partagé :
- Réécrire l'historique (git filter-repo) POUR SUPPRIMER le fichier `.env` contenant les secrets.
- Ajouter bannière de disclosure dans README.

## 8. Regex couvertes (script)
- Clés hex longues (>=32)
- UUID v4 apparents
- Préfixes connus (CG-, tm-, pk_live_, sk_live_, etc.)
- API patterns (Infura 32 hex, Binance / Bybit tokens partiels)

## 9. Limitation
La détection heuristique peut produire des faux positifs. Maintenir une whitelist (hash partiel) si nécessaire.

## 10. Prochaines améliorations
- Intégration d'un scanner plus avancé (trufflehog / detect-secrets) en CI.
- Chiffrement facultatif de variables locales (sops + age).

---
Dernière mise à jour: généré automatiquement.

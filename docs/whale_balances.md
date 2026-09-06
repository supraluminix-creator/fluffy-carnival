# Whale Balances (ETH)

Ce guide résume la configuration et les outils autour de la collecte des soldes
ETH des "whales" (comptes à forte valeur) via Etherscan.

## Activation rapide

1. Exporter les variables d'environnement requises :
   - `ENABLE_WHALE_BALANCES=1`
   - `ETHERSCAN_ENABLED=1`
   - `ETHERSCAN_API_KEY=<votre clé>`
   - `ETHERSCAN_ADDRESSES=0xAAA,0xBBB` (CSV ou lignes séparées)
   - `ETHERSCAN_THRESHOLD_ETH=10` *(optionnel – filtre des transactions whale)*
   - `ETHERSCAN_EXPORT_DIR=exports/onchain` *(optionnel – chemin export)*
2. Lancer le pipeline (`python main.py`) ou le scheduler.
3. Vérifier l'export JSON `exports/onchain/etherscan_whale_balances.json`.

## Observation rapide

- **API REST** : `GET /api/whales/balances`
- **Métriques Prometheus** :
  - `whale_balance_total_eth`
  - `whale_balance_address_eth{address=...}`
  - `whale_balance_snapshot_timestamp`
- **CLI** : `python -m scripts.dump_whale_balances`
  - `--load-only` : lit le dernier snapshot sans rafraîchir.
  - `--json` : sortie brute JSON (incluant métadonnées).
  - `--top N` : limite le nombre d'adresses affichées (défaut : 10).

## Exemple de sortie CLI

```bash
$ python -m scripts.dump_whale_balances --load-only --top 5
Source       : etherscan
Generated at : 2025-10-24T18:42:36+00:00
Address count: 12
Total ETH    : 18245.1234
Fresh fetch  : no

Address                                       Balance ETH    Share
-----------------------------------------------------------------
0xabc...123                                       4200.5000   23.02%
0xdef...456                                       3500.0000   19.19%
...
```

## Dépannage

- **Pas de snapshot / 404 API** : vérifier que `ENABLE_WHALE_BALANCES` et
  `ETHERSCAN_ENABLED` sont positionnés, et que la clé Etherscan est valide.
- **Métriques obsolètes** : le collector réinitialise désormais les labels
  Prometheus pour éviter les adresses fantômes après un changement de liste.
- **Quota Etherscan** : ajuster `ETHERSCAN_SLEEP_MS` pour lisser les appels.

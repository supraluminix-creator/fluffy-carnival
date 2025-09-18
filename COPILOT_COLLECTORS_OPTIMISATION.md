# 🚀 Crypto Monitor – Sources, Timings & Collectors Optimisation

## 🎯 Objectif
Structurer le pipeline Python de monitoring crypto avec une gestion claire des **APIs principales (Main)**, **backups**, **quotas**, et **timings de rafraîchissement**.  
Ce document sert de guide pour **GitHub Copilot** afin d’optimiser les collectors et les intégrer proprement dans le projet.

---

## 📊 Recap APIs & Collectors

| API / Source          | Type de données       | Indicateurs collectés | Timing recommandé       | Quotas indicatifs       | Rôle |
|------------------------|----------------------|------------------------|-------------------------|-------------------------|------|
| CoinGecko              | Prix, macro, stablecoins | Prix BTC/ETH/SOL/LINK, vol 24h, cap, dominance, stablecoins supply | 300s (prix), 1800s (stablecoins) | 5–15 req/min (30/min payant) | Main |
| CoinMarketCap (CMC)    | Macro, prix, dominance | Cap global, dominance, ratios vol/MC | 300s | 300 req/min (1M/mois) | Backup |
| CryptoCompare          | Prix, historiques, échanges | Prix temps réel, OHLC minute (7j), vol par exchange | 300s (live), 3600s (histo) | 100k/mois ; 10/s | Main (prix/histo complément) |
| DefiLlama              | DeFi / TVL / liquidité | TVL, revenus, fees, users actifs | 900–1800s | 10–200/min (gratuit) | Main |
| Alternative.me         | Sentiment | Fear & Greed Index (0–100) | 3600s | Pas de quota | Main |
| Blockchain.info        | BTC on-chain | Hashrate, txcount, bloc | 300s | ~5/s | Main |
| Infura                 | ETH on-chain | Block height, tx count | 300s | 2000 crédits/s | Main |
| Etherscan              | ETH on-chain | Txcount, hashrate ETH | 300s | 5/s, 100k/jour | Backup |
| Bybit REST             | Dérivés | OI, Funding Rate, vol, prix | 300s | 600/5s (IP) | Main |
| Bybit WebSocket        | Dérivés temps réel | Liquidations BTC/ETH | Flux continu (flush 5s/100 events) | WebSocket | Main |
| Binance                | Dérivés | Liquidations, OI | 300s | 1200/min (20/s) | Backup |
| Mempool.space          | BTC mempool | Nb txs, fees, congestion | 300s | 60/min | Main |
| BGeometrics            | Bitcoin metrics | SOPR snapshot & historique, NUPL, MVRV, OI, FR | 300s snapshot ; 6h historique | 300/min (histo), 600+/min (snap) | Main |
| SOPR (bitcoin-data)    | On-chain ratio | SOPR global | 900s (15m, 4/h max) | 4/h | Backup |
| SOPR (Blockchain.info) | On-chain ratio | SOPR (7d) | 900s | Public | Backup |
| TokenMetrics           | Signaux trading | Signals, on-chain patterns | 3600s (1h) | quotas faibles | Main |

---

## ⏱️ Timings recommandés

- **Toutes les 5 min (300s)**  
  CoinGecko, CMC (backup), CryptoCompare (live prix), Blockchain.info, Infura, Etherscan (backup), Bybit REST, Binance (backup), Mempool.space, BGeometrics snapshot  
- **Toutes les 15–30 min (900–1800s)**  
  DefiLlama (TVL/liquidity), Stablecoins (CoinGecko macro), SOPR backups  
- **Toutes les 60 min (3600s)**  
  Fear & Greed (Alternative.me), TokenMetrics signals  
- **Temps réel**  
  Bybit WS liquidations BTC/ETH  
- **Toutes les 6h**  
  BGeometrics historiques lourds  

---

## 📚 Documentation technique

- CoinGecko → https://www.coingecko.com/en/api/documentation  
- CoinMarketCap → https://coinmarketcap.com/api/documentation/v1/  
- CryptoCompare → https://min-api.cryptocompare.com/documentation  
- DefiLlama → https://docs.llama.fi/  
- Alternative.me → https://alternative.me/crypto/fear-and-greed-index/  
- Blockchain.info → https://www.blockchain.com/api/blockchain_api  
- Infura → https://docs.infura.io/  
- Etherscan → https://docs.etherscan.io/  
- Bybit REST → https://bybit-exchange.github.io/docs/v5/rate-limit  
- Bybit WebSocket → https://bybit-exchange.github.io/docs/v5/websocket-api  
- Binance → https://binance-docs.github.io/apidocs/futures/en/  
- Mempool.space → https://mempool.space/docs/api  
- BGeometrics → https://charts.bgeometrics.com/bitcoin_api.html  
- SOPR (bitcoin-data) → https://github.com/bitcoin-data/sopr/blob/main/README.md  
- TokenMetrics → https://tokenmetrics.gitbook.io/tokenmetrics-api/  

---

## 📌 Instructions pour GitHub Copilot

1. Inspecter le code des **collectors existants**.  
2. Vérifier les appels API vs **tableau Main/Backup + quotas**.  
3. Ajouter optimisations :  
   - cache local (disk/memory)  
   - backoff exponentiel (retry safe quotas)  
   - fallback automatique (si Main échoue → Backup)  
   - parallélisation via `asyncio` + `httpx`  
4. Structurer par modules :  
   - `collectors/market.py` (CoinGecko, CMC, CryptoCompare)  
   - `collectors/defi.py` (DefiLlama)  
   - `collectors/onchain.py` (Blockchain.info, Infura, Etherscan, BGeometrics, SOPR)  
   - `collectors/derivatives.py` (Bybit REST, Binance)  
   - `collectors/ws.py` (Bybit WS)  
   - `collectors/sentiment.py` (Alternative.me, TokenMetrics)  
5. Ajouter docstrings clairs, logs structurés, métriques Prometheus, tests unitaires avec `pytest`.  
6. Respecter le **planning des timings** pour ne pas dépasser les quotas gratuits.  

---

## ✅ Résultat attendu

Un pipeline Python clair et modulaire, avec :
- Collectors robustes respectant quotas et timings  
- Fallback Main/Backup intégré  
- Documentation claire (docstrings, README)  
- Logs et monitoring intégrés  
- Prêt pour CI/CD avec GitHub Actions  

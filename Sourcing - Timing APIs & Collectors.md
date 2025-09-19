Source / Timing APIs & Collectors

reste pragmatique → je les intègre dans ton tableau avec leur rôle Main/Backup et les timings adaptés (sans flinguer les quotas gratuits).

📊 Recap APIs & Collectors (avec CryptoCompare + TokenMetrics inclus)
API / Source	Type de données	Indicateurs collectés	Timing recommandé	Quotas indicatifs	Rôle (Main / Backup)
CoinGecko	Prix, macro, stablecoins	Prix BTC/ETH/SOL/LINK, vol 24h, cap, dominance, stablecoins supply	300s (5 min) prix/macro ; 1800s stablecoins	5–15 req/min (30/min payant)	Main
CoinMarketCap (CMC)	Macro, prix, dominance	Cap global, dominance, ratios vol/MC	300s (5 min)	300 req/min (1M crédits/mois)	Backup
CryptoCompare	Prix, historiques, échanges	Prix en temps réel, OHLC minute (7j), vol par exchange	300s (5 min live), 3600s (1h pour historiques lourds)	100k req/mois ; 10 req/s	Main (prix/histo complément)
DefiLlama	DeFi / TVL / liquidité	TVL, revenus, fees, utilisateurs actifs	900–1800s (15–30 min)	10–200 req/min (gratuit), 1000 req/min (Pro)	Main (DeFi)
Alternative.me (Fear & Greed)	Sentiment	Fear & Greed Index (0–100)	3600s (1h)	Pas de quota dur	Main
Blockchain.info	BTC on-chain	Hashrate, txcount, dernier bloc	300s (5 min)	≈5 req/s	Main
Infura	ETH on-chain (RPC)	Block height, tx count, transactions	300s (5 min)	2000 crédits/s (free)	Main
Etherscan	ETH on-chain	Txcount, hashrate ETH	300s (5 min)	5 req/s, 100k/jour	Backup
Bybit (REST)	Dérivés	Open Interest, Funding Rate, vol, prix 24h	300s (5 min)	600 req / 5s (IP)	Main
Bybit (WS)	Dérivés temps réel	Liquidations BTC/ETH (side, qty, price)	Flux continu, flush 5s/100 events	WebSocket, pas de quota	Main (temps réel)
Binance	Dérivés	Liquidations, OI	300s (5 min)	1200 req/min (20/s)	Backup
Mempool.space	BTC mempool	Nb txs, fees, congestion	300s (5 min)	60 req/min	Main
BGeometrics	Bitcoin metrics étendus	SOPR snapshot & historique, NUPL, MVRV, OI, FR	300s (snapshot) ; 6h (historique)	~300 req/min (hist.), 600+/min (snap)	Main (SOPR & on-chain avancé)
SOPR (bitcoin-data)	On-chain ratio	SOPR global	900s (15 min, 4/h max)	4 req/h max	Backup
SOPR (Blockchain.info)	On-chain ratio	SOPR (7d)	900s (15 min)	Public	Backup
TokenMetrics	Signaux trading, sentiment	Trading signals, on-chain patterns, prix, indicateurs AI	3600s (1h) ou selon quota	Quotas faibles sur free, supérieurs en payant	Main (signals avancés)
⚖️ Arbitrage clair avec CryptoCompare & TokenMetrics

Prix & Historiques

CoinGecko = Main (macro/prix)

CryptoCompare = Main complémentaire (historique OHLC + exchanges)

CoinMarketCap = Backup

DeFi

DefiLlama = Main (TVL, revenus, fees)

On-chain BTC & ETH

Blockchain.info = Main BTC

Infura = Main ETH

Etherscan = Backup ETH

BGeometrics = Main (SOPR, NUPL, MVRV, hash, OI)

Dérivés

Bybit REST/WS = Main

Binance = Backup

Sentiment

Alternative.me = Main (Fear & Greed)

TokenMetrics = Main complémentaire (trading signals)

SOPR

BGeometrics = Main

bitcoin-data + Blockchain.info = Backups

⏱️ Planning pragmatique ajusté

Toutes les 5 min (300s)
CoinGecko, CMC (backup), CryptoCompare (live prix), Blockchain.info, Infura, Etherscan (backup), Bybit REST, Binance (backup), Mempool.space, BGeometrics snapshot

Toutes les 15–30 min (900–1800s)
DefiLlama (TVL/liquidity), Stablecoins (CoinGecko macro), SOPR backups

Toutes les 60 min (3600s)
Fear & Greed (Alternative.me), TokenMetrics signals

Temps réel
Bybit WebSocket (liquidations BTC/ETH)

Toutes les 6h
BGeometrics historiques lourds

👉 Avec ça tu as une stack très pro et équilibrée, qui :

Sépare bien Main vs Backup

Protège contre dépassements de quotas gratuits

Donne une vision complète (Macro + DeFi + On-chain + Dérivés + Sentiment + Signals AI)

Voici la liste pragmatique des liens vers les documentations officielles des APIs et collectors du tableau récapitulatif, dans l’ordre demandé, avec une vue claire sur le rôle et les timings recommandés :

API / Collector	Rôle	Timing recommandé	Documentation principale
CoinGecko	Main	300s (5 min), 1800s stablecoins	https://coingecko.com/en/api
CoinMarketCap (CMC)	Backup	300s (5 min)	https://coinmarketcap.com/api/documentation/v1/
CryptoCompare	Main	300s (5 min live), 3600s (historiques lourds)	https://www.cryptocompare.com/api#
DefiLlama	Main	900-1800s (15-30 min)	https://docs.llama.fi/pro-api
Alternative.me (Fear & Greed)	Main	3600s (1h)	https://alternative.me/fear-and-greed/
Blockchain.info	Main	300s (5 min)	https://www.blockchain.com/api
Infura	Main	300s (5 min)	https://infura.io/docs
Etherscan	Backup	300s (5 min)	https://docs.etherscan.io/api
Bybit (REST)	Main	300s (5 min)	https://bybit-exchange.github.io/docs/v5/rate-limit
Bybit (WebSocket)	Main (réel)	Flux continu, flush 5s/100 events	https://bybit-exchange.github.io/docs/v5/websocket-api
Binance	Backup	300s (5 min)	https://binance-docs.github.io/apidocs/futures/en/#rate-limits
Mempool.space	Main	300s (5 min)	https://mempool.space/api
BGeometrics	Main	300s (snapshot), 6h (historique)	https://charts.bgeometrics.com/bitcoin_api.html
SOPR (bitcoin-data)	Backup	900s (15 min)	Documentation interne ou API Blockchain.info (publique)
TokenMetrics	Main	3600s (1h) ou selon quota	https://www.tokenmetrics.com/api
Cette liste pragmatique inclus les liens utiles pour :

Accéder à la documentation API officielle,

Vérifier quotas et limites,

Adapter le timing de vos collectes pour ne pas dépasser les seuils gratuits,

Séparer clairement Main et Backup dans la gestion de la collecte.
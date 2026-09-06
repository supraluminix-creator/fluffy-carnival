# APIs – Inventaire et Quotas (Free tiers)

Ce document inventorie les APIs utilisées/prévues, leurs endpoints clés, quotas free, besoin de clé, et liens officiels.

| API | Endpoints clés | Données | Quota free (indicatif) | Clé | Notes | Doc |
|---|---|---|---:|:--:|---|---|
| CoinGecko | /api/v3/coins/{id} | Prix/vol/marketcap | ≈ 30-50/min | Non | Démo/public | https://www.coingecko.com/en/api/documentation |
| Binance | /api/v3/ticker/price, /fapi/v1/fundingRate | Spot, OI, Funding | Élevé (weights/limits) | Non | Public | https://www.binance.com/en/binance-api |
| Bybit | /v5/market/* | OI/LSR/Funding | Public | Non | Utilisé via façade | https://bybit-exchange.github.io/docs/v5/ |
| DefiLlama | /v2/chains, /v2/historicalChainTvl/{chain} | TVL | Public | Non | | https://defillama.com/docs/api |
| alternative.me | /fng/ | Fear & Greed | Public | Non | | https://alternative.me/crypto/fear-and-greed-index/ |
| Blockchain.info | /q/hashrate, /q/getblockcount | Hashrate/Txcount | Public | Non | | https://www.blockchain.com/explorer/api |
| Bitcoin-data.com | /v1/sopr/csv | SOPR | Public | Non | | https://bitcoin-data.com/ |
| Twelve Data | /time_series | Indices, DXY, Or | ≈ 800/j | Oui | Basic free | https://twelvedata.com/docs |
| Alpha Vantage | /query (TIME_SERIES_DAILY) | Indices/FX | ≈ 25/j | Oui | Très limité | https://www.alphavantage.co/documentation/ |
| BGeometrics | /api/mvrv-zscore | MVRV Z-Score | Limité | Non | Variabilité | https://charts.bgeometrics.com/bitcoin_api.html |
| Coinalyze | /v1/funding-rates | Funding dérivés | ≈ 40/min | Oui | Optionnel | https://api.coinalyze.net/v1/doc/ |
| Messari | /v2/assets/* | Premium | 2/j (AI free) | Oui | Backup | https://data.messari.io/docs/ |

Remarques: messari (AI free 2 req/j), TwelveData (≈800/j), AlphaVantage (≈25/j), Blockchair (soft 5 req/s, hard 30 req/min) selon docs officielles.

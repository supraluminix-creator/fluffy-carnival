# Data Mapping – Signaux ↔ Sources ↔ Champs

Format normalisé (tous collectors):
- timestamp: int|None (unix ms/s selon source, fallback None)
- asset: str (ex: BTC, sp500, dxy)
- metric_name: str (ex: macro, macro_index, funding_rate, open_interest, mvrv_z_score, sopr, hashrate, txcount)
- value: number|object (selon métrique; ex: {close} pour indices)
- source: str (provider)
- confidence_score: float

Correspondances principales:
- macro (CoinGecko): value.price, value.volume_24h, value.marketcap
- macro_index (sp500/nasdaq/dowjones/gold/dxy): value.close
- funding_rate (Bybit/Binance): value (float, %)
- open_interest (Bybit/Binance): value (float)
- long_short_ratio (Bybit): value.{buy_ratio,sell_ratio}
- tvl (DefiLlama): value (float)
- fear_greed: value (float index 0-100)
- hashrate: value (float)
- txcount: value (int)
- sopr: value (float)
- mvrv_z_score: value (float)

Sanity checks recommandés:
- Prix BTC Binance vs CoinGecko ±0.5%
- Funding rate |value| <= 1%
- Macro indices fraîcheur < 24h
- MVRV non-NaN et variation jour < seuil configurable

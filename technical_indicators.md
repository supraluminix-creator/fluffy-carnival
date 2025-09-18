README CALCULES !

→ avoir les **données brutes gratuites** (OHLC + volume), et construire toi-même les **indicateurs avancés**.

1. **Tableau enrichi** (APIs + données nécessaires pour calculer RSI, MACD, Bollinger, etc.)
2. **README.md** pédagogique, pour bien expliquer ta stack (où trouver les données, comment les calculer, exemple Python, etc.)

---

# 📊 Tableau enrichi : APIs + Données pour Indicateurs Pro

| API / Source               | Type de données                 | Données nécessaires pour TA                  | Quotas indicatifs              | Usage                  |
| -------------------------- | ------------------------------- | -------------------------------------------- | ------------------------------ | ---------------------- |
| **Binance** (API publique) | Spot & Futures OHLC + volume    | ✅ OHLC (1m → 1M) ; ✅ Volume                  | 1200 req/min (20/s)            | **Main pour TA**       |
| **Bybit REST**             | Futures/Spot OHLC + dérivés     | ✅ OHLC (1m → 1M) ; ✅ Funding Rate ; ✅ OI     | 600 req / 5s                   | **Main dérivés**       |
| **CryptoCompare**          | Historique prix OHLC            | ✅ OHLC minute (7j), heure, jour              | 100k/mois ; 10/s               | **Backup histo OHLC**  |
| **CoinGecko**              | Prix spot, historiques daily    | ❌ Pas OHLC granulaire (seulement daily)      | 5–15/min (free)                | **Macro / backup**     |
| **BGeometrics**            | On-chain BTC (SOPR, MVRV, NUPL) | ❌ Pas OHLC ; données chain metrics           | 300/min (hist), 600/min (snap) | **On-chain metrics**   |
| **TokenMetrics**           | Signals AI trading              | ❌ Pas OHLC ; indicateurs dérivés             | faible quotas                  | **Optionnel (payant)** |
| **Bybit WS**               | Liquidations temps réel         | ❌ Pas OHLC ; données flux (qty, side, price) | Flux continu                   | **Temps réel dérivés** |

---

# 📈 Indicateurs calculables avec ces données

| Indicateur          | Données nécessaires | API Sources gratuites         | Calcul en Python       |
| ------------------- | ------------------- | ----------------------------- | ---------------------- |
| **RSI**             | OHLC                | Binance, Bybit, CryptoCompare | `pandas-ta.rsi()`      |
| **MACD**            | OHLC                | Binance, Bybit, CryptoCompare | `pandas-ta.macd()`     |
| **Bollinger Bands** | OHLC                | Binance, Bybit, CryptoCompare | `pandas-ta.bbands()`   |
| **EMA / SMA**       | OHLC                | Binance, Bybit, CryptoCompare | `pandas-ta.ema()`      |
| **Ichimoku**        | OHLC                | Binance                       | `pandas-ta.ichimoku()` |
| **VWAP**            | OHLC + volume       | Binance, Bybit                | `pandas-ta.vwap()`     |
| **Funding Rate**    | Direct (REST)       | Bybit                         | Pas besoin de calcul   |
| **Open Interest**   | Direct (REST)       | Bybit                         | Pas besoin de calcul   |

---

# 📄 README.md (version initiale)

````markdown
# 📊 Crypto Monitor – Technical Indicators

## Objectif
Construire un pipeline Python de monitoring crypto combinant :
- **Prix & Macro** (CoinGecko, CMC)
- **On-chain** (Blockchain.info, Infura, Etherscan, BGeometrics)
- **Dérivés** (Bybit REST/WS, Binance backup)
- **DeFi** (DefiLlama)
- **Sentiment & Signals** (Alternative.me, TokenMetrics)
- **Indicateurs techniques (TA)** calculés en local

---

## 🔎 Où récupérer les données brutes (gratuitement)

- **Binance (API publique)** → OHLC de presque toutes les paires (1m → 1M), volume disponible, gratuit (1200 req/min).
- **Bybit REST** → OHLC spot/futures, Funding Rate et Open Interest directement.
- **CryptoCompare** → OHLC minute (7 jours d’historique), horaire et daily.
- **CoinGecko** → prix spot & historiques quotidiens (pas granulaire minute).
⚠️ Les exchanges **ne fournissent pas directement les indicateurs techniques (RSI, MACD, etc.)** → vous devez les calculer à partir des données OHLC.

---

## 📊 Indicateurs techniques calculés en Python

| Indicateur | Données nécessaires | Source | Calcul |
|------------|--------------------|--------|--------|
| RSI | OHLC | Binance, Bybit, CryptoCompare | `pandas-ta.rsi()` |
| MACD | OHLC | Binance, Bybit, CryptoCompare | `pandas-ta.macd()` |
| Bollinger Bands | OHLC | Binance, Bybit, CryptoCompare | `pandas-ta.bbands()` |
| EMA / SMA | OHLC | Binance, Bybit, CryptoCompare | `pandas-ta.ema()` |
| Ichimoku | OHLC | Binance | `pandas-ta.ichimoku()` |
| VWAP | OHLC + volume | Binance, Bybit | `pandas-ta.vwap()` |
| Funding Rate | direct | Bybit REST | pas besoin de calcul |
| Open Interest | direct | Bybit REST | pas besoin de calcul |

---

## 🛠️ Exemple en Python

```python
import pandas as pd
import pandas_ta as ta
import requests

# Exemple : récupérer BTC/USDT OHLC depuis Binance
url = "https://api.binance.com/api/v3/klines"
params = {"symbol": "BTCUSDT", "interval": "5m", "limit": 500}
data = requests.get(url, params=params).json()

# Transformer en DataFrame
df = pd.DataFrame(data, columns=[
    "timestamp","open","high","low","close","volume",
    "close_time","qav","num_trades","taker_base_vol","taker_quote_vol","ignore"
])
df["close"] = df["close"].astype(float)

# RSI (14 périodes)
df["RSI"] = ta.rsi(df["close"], length=14)

# MACD
macd = ta.macd(df["close"])
df = pd.concat([df, macd], axis=1)

print(df.tail())
````

👉 Résultat : **RSI, MACD, etc.** calculés en local, sans consommer de quotas coûteux.

---

## ✅ Conclusion pragmatique

* Tous les indicateurs utilisés par les pros (RSI, MACD, Bollinger, EMA, VWAP, Ichimoku) peuvent être **calculés gratuitement**.
* Il suffit de récupérer **OHLC depuis Binance / Bybit / CryptoCompare**.
* Les indicateurs « Buy/Sell prêts à l’emploi » (TokenMetrics) nécessitent un abonnement → mais la **stack open-source** couvre déjà 95% des besoins des traders pros.
* **Prochain ajout dans le pipeline** : un module `technical_indicators.py` qui calcule RSI, MACD, Bollinger, etc., intégré aux collectors existants.

---

📌 **Note** : Pour Binance, il faudra activer l’API une fois le **KYC validé**.

```

---

👉 Veux-tu que je te prépare directement le **module `technical_indicators.py`** (collector) prêt à plugger dans ton pipeline (avec fonctions `get_rsi`, `get_macd`, etc.) ou tu préfères attendre d’avoir ta clé Binance active ?
```

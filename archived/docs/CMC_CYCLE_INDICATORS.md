# CoinMarketCap – Crypto Market Cycle Indicators

Ce module collecte les indicateurs de cycle crypto via deux approches:

1) API interne non documentée (JSON):
   - URL: `https://api.coinmarketcap.com/data-api/v3/charts/crypto-market-cycle-indicators?convert=USD`
   - Extraction: `data.indicators`
2) Fallback scraping (sans JS):
   - Page: `https://coinmarketcap.com/charts/crypto-market-cycle-indicators/`
   - Extraction: contenu `<script id="__NEXT_DATA__">...</script>` puis
     `props.pageProps.initialState.charts.cryptoMarketCycleIndicators.data.indicators`

Sortie normalisée (liste):
- `indicator`: nom lisible
- `status`: statut texte (ex: undervalued, neutral, overvalued)
- `value`: valeur courante
- `thresholds`: bornes éventuelles
- `source`: "api" ou "scraper"

Cache disque (diskcache): TTL par défaut 1h, configurable via `CMC_CYCLE_CACHE_TTL`. Pour désactiver la lecture cache: `CMC_CYCLE_CACHE_DISABLE=1`.

CLI utilitaire:
```powershell
& ".\.venv\Scripts\python.exe" tools\dump_cmc_cycle_indicators.py --format json --out exports\cmc_cycle_indicators.json
& ".\.venv\Scripts\python.exe" tools\dump_cmc_cycle_indicators.py --format csv --out exports\cmc_cycle_indicators.csv
```

Intégration pipeline: appelez `fetch_cmc_cycle_indicators()` depuis un job planifié ou un exporteur dédié.

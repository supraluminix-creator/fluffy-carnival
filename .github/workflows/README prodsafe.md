# 🚀 new_crypto_prodsafe

## Objectif
Pipeline crypto collectors robuste, modulaire, monitoré, prêt production.

## Fonctionnalités
- Collectors prod-safe (async, fallback, retry, cache, logs, métriques Prometheus)
- Export CSV harmonisé, reporting PowerShell-friendly
- Orchestration asynchrone, respect des quotas
- CI/CD GitHub Actions (tests auto)
- Documentation et versioning

## Collectors
- Macro (CoinGecko → CMC)
- DeFi (DefiLlama)
- On-chain (Blockchain.info, Etherscan, BGeometrics, SOPR)
- Dérivés (Bybit, Binance)
- Sentiment (Alternative.me, TokenMetrics)
- WebSocket (Bybit, à venir)

## Lancer le pipeline
```bash
python main.py
```

## Lancer les tests
```bash
pytest -q
```

## Visualiser les métriques
Prometheus scrape sur http://localhost:8000

## Structure export CSV
Champs : timestamp, asset, symbol, chain, metric_name, value, source, confidence_score

## CI/CD
- Lint, tests, coverage à chaque push/PR (voir `.github/workflows/ci.yml`)

## Roadmap
- Ajout Bybit WS, SOPR avancé, tests de charge, monitoring Grafana, alerting.

---

© 2025 new_crypto_prodsafe
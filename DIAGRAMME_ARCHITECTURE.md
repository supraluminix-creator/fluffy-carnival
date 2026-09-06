# 📊 Diagramme Technique — new_crypto_prodsafe

```mermaid
graph TD
    A[main.py] --> B[reporter.py]
    A --> C[exporter.py]
    A --> D[collectors]
    D --> D1[sopr_bgeometrics.py]
    D --> D2[sopr_blockchain.py]
    D --> D3[bybit_ws.py]
    D --> D4[defillama.py]
    D --> D5[txcount.py]
    D --> D6[hashrate.py]
    D --> D7[altme.py]
    A --> E[storage]
    E --> E1[sqlite_adapter.py]
    E --> E2[migrations.py]
    A --> F[SQLite (def. data/crypto.db)]
    A --> G[exports/latest_export.csv]
    A --> G2[exports/pipeline_export_<timestamp>.csv]
    A --> H[tests]
    H --> H1[test_collectors.py]
    H --> H2[test_signals.py]
    H --> H3[test_exporter.py]
```

- **main.py** : Orchestrateur, intègre tous les modules
- **reporter.py** : Affichage PowerShell-friendly
- **exporter.py** : Export CSV consolidé
- **collectors/** : Modules spécialisés multi-API
- **storage/** : Adaptateur SQLite, migrations
- **tests/** : Couverture unitaire et intégration
- **exports/** : Fichiers CSV produits
- **data/** : Base SQLite (défaut, overridable via `CRYPTO_DB_PATH`)

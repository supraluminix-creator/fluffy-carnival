# Schéma SQLite (pipeline)

## Tables principales

### bybit_liquidations
Événements bruts de liquidations Bybit (granularité événement).

| Colonne | Type | Unité / Format | Description |
|---------|------|----------------|-------------|
| time | INTEGER | millisecond epoch | Timestamp événement (ms). Index de filtrage temporel. |
| symbol | TEXT | ex: BTCUSDT | Instrument. |
| side | TEXT | 'Buy' / 'Sell' (si exposé). |
| price | REAL | prix exécution | Prix liquidation. |
| qty | REAL | quantité (contrats ou token) | Taille liquidation brute. |
| value_usd | REAL | USD notionnel approx | Qty * price (ou valeur fournie). |

Index recommandés:
- `CREATE INDEX IF NOT EXISTS idx_liq_time ON bybit_liquidations(time);`
- `CREATE INDEX IF NOT EXISTS idx_liq_symbol_time ON bybit_liquidations(symbol, time);`

### bybit_liquidations_hourly
Agrégations horaires (window: [hour_start, hour_start+3600)).

| Colonne | Type | Unité | Description |
|---------|------|-------|-------------|
| hour_start | INTEGER | epoch seconds | Début heure UTC (floor). PK partielle avec symbol. |
| symbol | TEXT | | Instrument. |
| total_events | INTEGER | | Nombre événements dans l'heure. |
| total_value_usd | REAL | USD | Somme notionnelle. |
| max_single_liq_usd | REAL | USD | Plus grosse liquidation dans l'heure. |
| last_update_ts | INTEGER | epoch seconds | Timestamp dernière mise à jour de cette agrégation. |

Clé/Contrainte:
`PRIMARY KEY(hour_start, symbol)` (upsert ON CONFLICT pour agrégation incrémentale).

### Métadonnées / autres (potentielles)
Aucune table de migration pour l'instant (évolution simple). Créer à terme une table `schema_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER)` si migrations complexes.

## Considérations de conception
- Format lean (réduit fragmentation) : pas de TEXT volumineux.
- Agrégation horaire réduit volume pour tableaux de bord (P95 sur 30j allégé).
- Vacuum conditionnel (cf. maintenance) basé sur ratio fragmentation.

## Évolution schéma (good practices)
1. Ajouter d'abord colonne nullable avec valeur par défaut logique.
2. Backfill progressif si nécessaire (scripts isolés). 
3. Exposer nouveau champ dans export/contrat seulement après déploiement complet.
4. Mettre à jour tests de contrat CSV (voir TODO correspondant) pour empêcher suppression / renommage silencieux.

## Roadmap schéma
- Index composite pour requêtes analytiques (symbol + time range) déjà présent.
- Table de dérivés quotidiens potentielle (agrégation journalière). 
- Historisation métadonnées latence (éventuelle table `collector_latency(hour_start, collector, p95_ms)`).

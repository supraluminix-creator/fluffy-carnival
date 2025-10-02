# 🏗️ Vue d'ensemble Architecture — Crypto Monitor (à date)

## Diagramme synthétique

```mermaid
graph TB
    subgraph "🌐 External APIs"
        A1[CoinGecko]
        A2[CoinMarketCap]
        A3[DefiLlama]
        A4[Bybit REST]
        A5[Bybit WebSocket]
        A6[Alternative.me]
        A7[Blockchain.info]
        A8[Etherscan]
    end

    subgraph "⚡ new_crypto_prodsafe"
        subgraph "📊 Collectors"
            B1[Market]
            B2[Defi]
            B3[Onchain]
            B4[Derivatives]
            B5[Sentiment]
            B6[WS (Bybit)]
        end

        subgraph "🗄️ Storage"
            C1[SQLite]
            C2[Parquet]
            C3[DiskCache]
        end

        subgraph "📤 Export"
            D1[CSV Exports]
        end

        subgraph "🔍 Observability"
            E1[Structlog JSON]
            E2[Prometheus Metrics]
            E3[/health, /ready, /live]
            E4[/metrics/ready]
        end

        subgraph "⏰ Scheduler"
            S1[APScheduler]
            S2[jobs.yaml]
        end
    end

    A1-->B1; A2-->B1; A3-->B2; A4-->B4; A5-->B6; A6-->B5; A7-->B3; A8-->B3
    B1-->C1; B2-->C1; B3-->C1; B4-->C1; B5-->C1; B6-->C1
    C1-->D1
    B1-->E1; B1-->E2; B6-->E1; B6-->E2
    S2-->S1; S1-.triggers.->B1; S1-.triggers.->B2; S1-.triggers.->B3; S1-.triggers.->B4; S1-.triggers.->B5
```

---

## Tableau santé (résumé)

| Dimension | Santé | Observations |
|---|---|---|
| Résilience | Bon | Jitter, retries, persistance compteurs. Manque budgets/CB. |
| Observabilité | Très bon | Logs JSON, run_id, metrics, /health, /metrics/ready. |
| Tests | Moyen | Présence utile; manque tests de config/health/schema. |
| Secrets | Correct | Env OK; CI secrets non vérifiés. |
| Scalabilité | Moyen | Async OK; parallélisme et limites par source à cadrer. |
| Maintenabilité | Bon | Modules clairs; réduire modes historiques. |

---

## Top‑risks (3)

1. Modes multiples et dérives de config (Critical)
2. Schéma données export non contractuel (High)
3. Politique HTTP non unifiée (timeouts/retry) (High)

## Top quick‑wins (3)

1. Boot banner + validation YAML (Critical)
2. Pydantic schema pour exports + tests golden (High)
3. Client HTTP unifié + métriques dédiées (High)
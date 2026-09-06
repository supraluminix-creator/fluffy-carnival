# Intégration Grok (opt‑in)

Cette intégration ajoute une couche "sentiment / narratif social" à partir de Grok (XAI). Elle est désactivée par défaut et n’ajoute aucune dépendance.

## Activation (env)

Renseignez les variables suivantes (dans `.env.local` ou via `$env:`) avant d'exécuter l'adapter :

| Variable | Requis | Description | Exemple / Défaut |
| --- | --- | --- | --- |
| `GROK_ENABLED` | Oui | Active l'intégration (`1` pour activer). | `1` |
| `GROK_API_KEY` | Oui | Clé API XAI permettant d'appeler Grok. | `sk-live-xxxxxxxx` |
| `GROK_API_BASE` | Non | URL de base alternative si vous utilisez un proxy. | `https://api.x.ai` |
| `GROK_API_ENDPOINT` | Non | Endpoint relatif si différent de `/v1/sse`. | `/v1/sse` |
| `GROK_WINDOW` | Non | Fenêtre temporelle agrégée (`1h`, `4h`, `24h`). | `1h` |
| `GROK_LIMIT` | Non | Nombre max d'éléments renvoyés. | `50` |
| `GROK_CACHE_TTL` | Non | TTL en secondes du cache local. | `900` |
| `GROK_ASSETS` | Non | Liste d'actifs ciblés, séparés par des virgules. | `BTC,ETH,SOL` |

Voir `.env.local.example` pour une base pré-remplie.

## Rafraîchir le sentiment

Via la tâche VS Code "Grok: refresh social sentiment". Le script `scripts/grok_refresh.py`:

- lit GROK_ASSETS (ex: BTC,ETH)
- appelle `integrations.grok_adapter.get_social_signals()`
- écrit le JSON dans `exports/social/latest_grok_<window>.json`

## Données produites (exemple)

```json
{
  "ts": 1728720000,
  "window": "1h",
  "assets": ["BTC","ETH"],
  "items": [
    {"asset":"BTC","sentiment":0.42,"trends":["#btc","halving"],"examples":["..."],"source":"xai"}
  ],
  "meta": {"enabled": true, "source": "grok"}
}
```

## Notes

- Si GROK_ENABLED=0 ou clé absente, un payload vide est écrit (dégradé non bloquant).
- L’adapter utilise la façade HTTP unifiée (retries/backoff/metrics globaux).
- Un cache fichier avec TTL limite les appels; `GROK_FORCE=1` dans l’environnement force un rafraîchissement.

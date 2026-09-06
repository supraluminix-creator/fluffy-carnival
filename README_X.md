# X (Twitter) — adapter opt-in (curated feed)

Cet adapter interroge l’API v2 de X (search recent) sur une watchlist ciblée (hashtags et comptes) et écrit un export JSON local. Désactivé par défaut.

## Activer et configurer

1) Renseignez les variables suivantes dans `.env.local` (ou via `$env:`). Toutes les valeurs doivent être en texte brut, sans guillemets :

| Variable | Requis | Description | Exemple / Valeur par défaut |
| --- | --- | --- | --- |
| `X_ENABLED` | Oui | Active l'adapter (`1` pour activer, `0` pour désactiver). | `1` |
| `X_BEARER_TOKEN` | Oui | Jeton **OAuth2 Bearer** obtenu sur le portail développeur X. | `AAAAAAAA...`
| `X_WATCHLIST` | Oui | Liste séparée par des virgules de hashtags (`#BTC`) et/ou handles (`@binance`). Minimum un élément. | `#BTC,#ETH,@binance`
| `X_LIMIT` | Non | Nombre max de messages récupérés (1–100). | `50` |
| `X_TIMEOUT` | Non | Timeout HTTP en secondes. | `12` |
| `X_CACHE_TTL` | Non | Durée du cache local en secondes. | `900` |
| `X_DISABLE_SEARCH` | Non | Mettre `1` pour ignorer les recherches hashtag si votre plan ne le permet pas. | `0` |
| `X_USE_LANG` | Non | Forcer la détection de langue (`1`) ou la désactiver (`0`). | `1` |
| `X_EXCLUDE_RETWEETS` | Non | Filtrer les retweets (`1`) ou les inclure (`0`). | `1` |
| `X_PACING_MS` | Non | Pause en millisecondes entre deux requêtes pour respecter les quotas. | `200` |
| `X_SELECTOR` | Non | Stratégie de rotation de la watchlist. Valeurs acceptées : `handles-first`, `hashtags-first`, `random`, `roundrobin`. | `handles-first` |
| `X_RATE_WINDOW_APP_SEC` | Non | Fenêtre de quotas (app) en secondes. | `900` |
| `X_RATE_WINDOW_USER_SEC` | Non | Fenêtre de quotas (token) en secondes. | `900` |

2) Préparez votre watchlist (copier-coller possible) :

```env
X_WATCHLIST="#BTC,#ETH,#SOL,#Altcoins,#Crypto,#DeFi,#Airdrop,@binance,@cz_binance,@CoinMarketCap,@APompliano,@WatcherGuru,@AltcoinDaily,@CryptoKaleo,@WuBlockchain,@TheBlock__,@BitcoinMagazine"
```

Note: vous pouvez ajouter d’autres hashtags (p. ex. `#XRP,#ADA,#LINK,#DOT`) ou comptes.

## Lancer depuis VS Code

- Tâche: «X: refresh curated feed» (ajoutée dans `.vscode/tasks.json`)
- Écrit: `exports/social/latest_x_curated.json`

## Lancer en ligne de commande (PowerShell)

```powershell
$env:X_ENABLED='1'; $env:X_BEARER_TOKEN='<VOTRE_TOKEN>'; $env:X_WATCHLIST='#BTC,#ETH,@binance'; \
  & '.\.venv\Scripts\python.exe' scripts\x_refresh.py
```

- Remplacez `<VOTRE_TOKEN>` par votre jeton Bearer exact (sans guillemets).
- Adaptez `X_WATCHLIST` au besoin avant d'exécuter la commande.

## Contrat de sortie

- JSON: `{ ts, queries, items: [ { id, text, created_at, lang, author, metrics, matched, source } ], meta }`
- `matched.type` ∈ {"user","hashtag"}
- `author.followers` si disponible

## Bonnes pratiques et quotas (free tier)

- Watchlist courte (10–20 tokens) pour rester sous les limites gratuites.
- Le script embarque un cache (TTL) et un parallélisme limité (2) pour éviter le rate‑limit.
- Si votre plan n’inclut pas la “Recent Search” v2, mettez `X_DISABLE_SEARCH=1` :
  - les hashtags seront ignorés (pas d’alternative sans search),
  - les handles `@user` seront récupérés via la timeline utilisateur (`/2/users/{id}/tweets`).
- En mode Search activé, si la première requête hashtag échoue, la recherche est désactivée dynamiquement pour le reste du run (meta.search_disabled_dynamic= true), et seules les timelines @user sont utilisées.
 - Le quota est persistant: 1 requête par fenêtre app, 1 par token. Un seul token est rafraîchi par run; le reste provient des caches par token.

## Mode Retweeters (optionnel)

Pour auditer un tweet et récupérer ses retweeters:

```
X_MODE=retweeters
X_RETWEETERS_TWEET_ID=<tweet_id>
```

L’adapter fera au plus 1 appel à `GET /2/tweets/:id/retweeted_by` par run en respectant les quotas. Les résultats sont stockés dans un cache dédié au token `tweet:<id>` et fusionnés dans l’export.
- L’absence de token, la désactivation ou une watchlist vide produit un export vide avec `meta.reason`.

## Sécurité

- Ne committez jamais vos tokens. Utilisez `.env.local` (non versionné) ou variables d’environnement.

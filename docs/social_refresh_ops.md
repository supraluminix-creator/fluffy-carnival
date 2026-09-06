# Social Refresh Ops (Windows)

Ce guide résume comment faire tourner l’adapter X (curated feed) et le mode retweeters 24/7 sous Windows, avec logs et planification, sans complexifier le projet.

## Pré-requis
- Python 3.12 + venv `.venv` avec dépendances installées.
- Fichier `.env.local` à la racine du repo (non versionné).

## Variables d’environnement clés
- X (obligatoire pour feed/retweeters):
  - `X_ENABLED=1`
  - `X_BEARER_TOKEN=<token>`
  - `X_WATCHLIST=#BTC,@binance,...` (pour le feed)
  - Quotas et options robustes recommandées:
    - `X_DISABLE_SEARCH=1` (si pas d’accès Recent Search v2)
    - `X_SELECTOR=handles-first`
    - `X_RATE_WINDOW_APP_SEC=900` et `X_RATE_WINDOW_USER_SEC=900`
  - Retweeters (optionnel):
    - `X_MODE=feed` (par défaut)
    - `X_RETWEETERS_TWEET_ID=<id>` (obligatoire quand `X_MODE=retweeters`)
- Grok (optionnel):
  - `GROK_ENABLED=1`
  - `GROK_API_KEY=<clé>`

Éviter les commentaires en fin de ligne pour les numériques (ex: `X_TIMEOUT=10`, pas `X_TIMEOUT=10 # ...`).

## Exécutions manuelles
- Feed + Grok (si activé):
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\run_social_refresh.ps1
  ```
- Retweeters (forcer le mode pour ce run):
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\run_x_retweeters.ps1
  ```
- Health-check (exécution manuelle rapide):
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\run_social_health_check.ps1
  ```

## Planification (Windows Task Scheduler)
- Créer la tâche périodique (15 min) + auto-démarrage:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\schedule_social_refresh.ps1
  ```
  - En admin: crée ONSTART + tâche 15 min.
  - Sans admin: crée tâche 15 min + raccourci dans Startup.

- Activer retweeters quotidien (ex: 10:30):
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\schedule_social_refresh.ps1 -EnableRetweetersDaily -DailyTime 10:30
  ```

- Activer le health-check périodique (ex: toutes les 30 min):
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\schedule_social_refresh.ps1 -EnableHealthCheck -HealthEveryMinutes 30
  ```

- Nettoyer (idempotent):
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\schedule_social_refresh.ps1 -Remove
  ```

## Logs et exports
- Logs (rotation auto 1 Mo):
  - Feed/Grok: `logs\social_refresh.log` (+ `.1`)
  - Retweeters: `logs\x_retweeters.log` (+ `.1`)
- Exports:
  - Feed: `exports\social\latest_x_curated.json`
  - Grok: `exports\social\latest_grok_<window>.json`

## Health-check de fraicheur
- Script: `scripts\social_health_check.py`
- Runners: `scripts\run_social_health_check.ps1` et `scripts\run_social_health_check.bat` (avec logs/rotation)
- Paramètres (env):
  - `SOCIAL_HEALTH_DIR` (par défaut `run/social`)
  - `SOCIAL_HEALTH_MAX_AGE_FEED_SEC` (par défaut 3600)
  - `SOCIAL_HEALTH_MAX_AGE_RETWEETERS_SEC` (par défaut 172800)
  - `SOCIAL_HEALTH_ALLOW_MISSING_FEED=1` pour tolérer l'absence de `last_success_feed.json` (utile si X_ENABLED=0)
- CLI (flags):
  - `--dir`, `--max-age-feed`, `--max-age-retweeters`
  - `--allow-missing-feed` | `--no-allow-missing-feed`
  - Les valeurs par défaut proviennent des variables d’environnement ci-dessus.
- Exemples:
  ```powershell
  $env:SOCIAL_HEALTH_MAX_AGE_FEED_SEC=1800; $env:SOCIAL_HEALTH_DIR="run/social"; python scripts\social_health_check.py
  $env:SOCIAL_HEALTH_ALLOW_MISSING_FEED=1; python scripts\social_health_check.py
  ```
- Codes de sortie: 0 (OK), 1 (problème)

## Dépannage rapide
- Chemins avec espaces: gérés via wrappers `.bat`.
- `.env.local` chargé par les scripts PowerShell, sans commentaires inline sur numériques.
- Sans token ou ID manquant (retweeters): le run logue un message explicite.
- `-Remove` est sûr même si les tâches n’existent pas.

## Bonnes pratiques
- Conserver `X_DISABLE_SEARCH=1` et `X_SELECTOR=handles-first` si votre plan n’a pas Recent Search v2.
- Laisser `X_RATE_WINDOW_APP_SEC` et `X_RATE_WINDOW_USER_SEC` à 900 (15 min) pour respecter 1 requête par fenêtre (app + token).
- Garder ces scripts isolés du scheduler Python pour maximiser la robustesse ops.

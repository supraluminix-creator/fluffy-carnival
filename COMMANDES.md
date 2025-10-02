# COMMANDES – Installation, configuration, exécution

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -r requirements.txt
```

## Configuration

- Créez un fichier `.env` (optionnel) avec:
  - ENABLE_METRICS=1 (pour exposer /metrics si API lancée)
  - ENABLE_MACRO_INDICES=0|1
  - ENABLE_MVRV_COLLECTOR=0|1
  - TWELVEDATA_API_KEY=...
  - ALPHAVANTAGE_API_KEY=...

## Lancer une collecte one-shot

```powershell
.\.venv\Scripts\python.exe cli_collect_once.py
```

## Lancer tous les tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Vérifier fraîcheur des exports

```powershell
.\.venv\Scripts\python.exe tools\check_freshness.py
```

## Activer le debug

- Définir `LOG_LEVEL=DEBUG`
- Pour forcer la façade HTTP: `FORCE_HTTP_FACADE=1`

## Rollback

- Revenir au précédent export en renommant `exports/latest_export.csv` avec un fichier timestampé stable.
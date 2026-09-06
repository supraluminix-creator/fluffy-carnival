# Indicateurs techniques (CSV/Parquet)

Ce module fournit un générateur d'indicateurs techniques basé sur pandas-ta (dépendance optionnelle), avec option d'export CSV ou Parquet et un audit automatique.

## Génération

- Source synthétique (offline, stable):

```powershell
& ".\.venv\Scripts\python.exe" tools\generate_indicators_csv.py --source synthetic --symbol BTCUSDT --interval 1h --limit 300 --indicators rsi,ema,macd,bbands,atr,stoch,adx,cci,roc,obv,adl,kc
```

- Source binance (réseau) avec retry + fallback et Parquet:

```powershell
& ".\.venv\Scripts\python.exe" tools\generate_indicators_csv.py --source binance --symbol BTCUSDT --interval 1h --limit 300 --out-format parquet --binance-timeout 10 --binance-retries 2 --indicators rsi,ema,macd,bbands,atr,stoch,adx,cci,roc,obv,adl,kc
```

La commande retourne un JSON donnant `path`, `row_count`, `columns`, `sha256` et `format`. Un manifest est aussi enregistré dans `exports/indicators/indicators_manifest.jsonl`.

## Audit

Vérifie les exports core (latest/timestamped) et la base SQLite, puis le dernier export d'indicateurs (CSV ou Parquet):

```powershell
& ".\.venv\Scripts\python.exe" tools\data_quality_audit.py
```

- Générer un rapport HTML minimal en plus du JSON:

```powershell
& ".\.venv\Scripts\python.exe" tools\data_quality_audit.py --html
```

Par défaut, le rapport est écrit dans `exports/indicators/report.html`. Vous pouvez changer le chemin via:
- l’option `--html-path`, ou
- la variable d’environnement `INDICATORS_AUDIT_HTML_PATH`.

Quand `--html` est utilisé, le JSON imprimé expose aussi le champ `html_report_path` pour retrouver facilement le rapport généré.

- Options complémentaires utiles:
  - `--no-fail-exit`: force un code de sortie 0 même si `status` est `FAIL` (utile pour l’observabilité/CI non bloquante).
  - `--report-name <nom>`: définit le nom du fichier HTML si `--html-path` n’est pas fourni (ex: `--report-name report_btc_1h`).
  - `--json-out <chemin>`: écrit le résultat JSON dans un fichier (en plus de l’impression standard).
  - `--print-tips`: affiche sur stderr un bref aide-mémoire (seuils, commandes utiles) — activé automatiquement si `status = FAIL`.
  - `--warmup-rows <N>`: nombre de lignes ignorées en début de série pour calculer les ratios (défaut: `$INDICATORS_WARMUP_ROWS` ou `50`).
    - `--lenient-timestamps`: tolère des timestamps non standards (désactive les erreurs `bad_timestamp`).
  - `--skip-csv`, `--skip-db`, `--skip-indicators`: sautent respectivement les validations CSV core, SQLite et indicateurs.
  - `--tag <valeur>`: tag libre (ex: nom d’env/profil) inclus dans le JSON et le HTML.
  - L’outil écrit une ligne informative sur stderr avec le chemin du HTML, pour éviter de polluer le JSON stdout.

- Écriture automatique d’un JSON à côté du HTML (optionnelle):

  Activez la variable d’environnement pour écrire par défaut `exports/indicators/report.json` quand `--html` est utilisé:

  ```powershell
  $env:INDICATORS_AUDIT_JSON_DEFAULT = "1"
  & ".\.venv\Scripts\python.exe" tools\data_quality_audit.py --html
  ```
  Le chemin sera aussi présent dans la sortie JSON sous `json_report_path`.
  Le rapport HTML inclut un lien cliquable vers ce JSON.

- Le ratio de non-NaN post-warmup (50 lignes) est exigé à 0.8 par défaut. Modifiable via la variable d'environnement `INDICATORS_NON_NAN_MIN` (ex: `0.7`).
 - Si la colonne `RSI` est présente, une vérification tolérante valide que la majorité des valeurs post-warmup sont dans [0,100].
   Le seuil de ratio minimal est `0.9` par défaut et peut être ajusté via `INDICATORS_RSI_BOUNDS_MIN`.
 - Si la colonne `ATR` est présente, un contrôle vérifie que la plupart des valeurs post-warmup sont ≥ 0.
   Le seuil de ratio minimal est `0.95` (modifiable via `INDICATORS_ATR_NONNEG_MIN`).
 - Si des colonnes Stochastiques sont présentes (préfixe `STOCH`), un contrôle valide que la majorité des valeurs post-warmup sont dans [0,100].
   Le seuil par défaut est `0.9` (modifiable via `INDICATORS_STOCH_BOUNDS_MIN`).
 - Si des bandes de Bollinger sont présentes (BBL/BBM/BBU, même suffixe), un contrôle valide que `BBL ≤ BBM ≤ BBU`.
   Le seuil par défaut est `0.95` (modifiable via `INDICATORS_BB_BOUNDS_MIN`).

### Tolérance symboles (Option B)

Certains exports historiques peuvent contenir des symboles en minuscule. Pour éviter des faux positifs côté audit CSV, utilisez l’un des mécanismes suivants:

- Passer le flag CLI `--lenient-symbols` à `tools/data_quality_audit.py`.
- Ou définir la variable d’environnement `INDICATORS_CSV_SYMBOL_UPPER_STRICT=0`.

Exemple:

```powershell
& ".\.venv\Scripts\python.exe" tools\data_quality_audit.py --html --print-tips --no-fail-exit --lenient-symbols
```

## Métriques (optionnel)

Des métriques Prometheus autour du calcul des indicateurs existent, mais sont désactivées par défaut. Pour les activer:

```powershell
$env:INDICATORS_METRICS = "1"
```

## Notes

- pandas-ta, pyarrow/fastparquet sont optionnels pour garder le noyau prod-safe vert.
- L'export Parquet nécessite `pyarrow` ou `fastparquet`.
- Les tâches VS Code incluent:
  - `Indicators: Generate`
  - `Indicators: Generate (synthetic, parquet)`
  - `Indicators: Generate (synthetic, parquet) + Audit`
  - `Indicators: Audit`
  - `Indicators: Audit (HTML report)`
  - `Indicators: Generate (synthetic) + Audit (HTML)`
  - `Indicators: Open latest HTML report`
  - `Indicators: Audit (HTML) + Open report`
  - `Indicators: Audit (HTML, no-fail)`
  - `Indicators: Audit (HTML, no-fail) + Open report`
  - `Indicators: Audit (HTML + tips + lenient symbols + json default)`
  - `Indicators: Generate + Audit`
  - `Indicators: Generate (binance+fallback, parquet)`
  - `Indicators: Generate (binance+fallback) + Audit (parquet)`

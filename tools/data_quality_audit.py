# ruff: noqa: E501

"""Audit des exports core et des fichiers d'indicateurs.

Ce script consolide plusieurs vérifications prod-safe:
    - CSV core: cohérence d'entête, valeurs numériques, unicité heuristique, strict/lenient sur symboles, timestamps
    - Base SQLite: tables attendues et échantillons plausibles (schéma/valeurs)
    - Indicateurs (CSV/Parquet): ratios de complétude/validité par métrique (RSI/ATR/Stoch/BB), warmup configurable
    - Rapport HTML optionnel (avec liens) et payload JSON (stdout et/ou fichier sidecar)

Il est conçu pour être:
    - tolérant en local (flags --no-fail-exit, --lenient-symbols, --lenient-timestamps)
    - stricte en CI (seuils via env; exit code 1 si FAIL par défaut)

Aucun changement fonctionnel n'est introduit par cette passe: seules des annotations
et docstrings clarifient l'intention et les formats manipulés.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import gnupg
    GPG_AVAILABLE = True
except ImportError:
    GPG_AVAILABLE = False

try:
    from pipeline.storage.sqlite_adapter import get_default_db_path
    PIPELINE_AVAILABLE = True
except ImportError:
    PIPELINE_AVAILABLE = False
    def get_default_db_path():
        # Fallback when pipeline is not available
        return "data/bybit_liquidations.db"

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORTS_DIR = REPO_ROOT / "exports"
TOOL_VERSION = "1.0.0"


def _validate_table_name(name: str) -> bool:
    """Validate table name to prevent SQL injection (paranoid check)."""
    if not name or not isinstance(name, str):
        return False
    # Allow alphanumeric, underscore, hyphen (common in table names)
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', name))


def _parse_iso8601(s: str) -> datetime | None:
    """Parsage tolérant de timestamps en chaîne.

    Accepte:
      - ISO8601 avec suffixe Z (UTC)
      - ISO8601 sans timezone (forcée en UTC)
      - Epoch en secondes (10 chiffres) ou millisecondes (>=13 chiffres)

    Args:
        s: chaîne de timestamp
    Returns:
        datetime en UTC si parsable, sinon None
    """
    with contextlib.suppress(Exception):
        # Accept Z suffix and offset-less
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1]).replace(tzinfo=UTC)
        # Accept pure epoch seconds or milliseconds
        if s.isdigit():
            val = int(s)
            # Heuristic: 10 digits -> seconds, 13 digits -> milliseconds
            secs = val / 1000.0 if len(s) >= 13 else float(val)
            return datetime.fromtimestamp(secs, tz=UTC)
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return None


def _read_latest_manifest() -> dict[str, Any] | None:
    """Lit le dernier enregistrement du manifeste core (append-only JSONL).

    Fichier: exports/export_manifest.jsonl

    Returns:
        dict | None: dernier enregistrement (paths, row_count, sha256) ou None.
    """
    mpath = EXPORTS_DIR / "export_manifest.jsonl"
    if not mpath.exists():
        return None
    last: dict[str, Any] | None = None
    with mpath.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(Exception):
                last = json.loads(line)
    return last


def _read_latest_indicators_manifest() -> dict[str, Any] | None:
    """Lit le dernier enregistrement du manifeste indicateurs (JSONL).

    Fichier: exports/indicators/indicators_manifest.jsonl

    Returns:
        dict | None: dernier enregistrement (path, format, sha256, columns) ou None.
    """
    mpath = EXPORTS_DIR / "indicators" / "indicators_manifest.jsonl"
    if not mpath.exists():
        return None
    last: dict[str, Any] | None = None
    with mpath.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(Exception):
                last = json.loads(line)
    return last


def _sha256_file(path: Path) -> str:
    """Calcule le hash SHA-256 d'un fichier (hex)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_csv(
    path: Path,
    expected_headers: list[str],
    *,
    strict_symbol_upper: bool | None = None,
    lenient_timestamps: bool = False,
) -> dict[str, Any]:
    """Valide un CSV core avec heuristiques simples.

    Args:
        path: chemin du CSV
        expected_headers: ordre exact attendu des colonnes
        strict_symbol_upper: si True, exige symboles en uppercase (prioritaire sur l'env)
        lenient_timestamps: si True, ne remonte pas l'erreur pour timestamps non parsables
    Returns:
        Détails de validation: {path, exists, rows, errors: list}
    """
    res: dict[str, Any] = {"path": str(path), "exists": path.exists(), "rows": 0, "errors": []}
    if not path.exists():
        res["errors"].append("csv_not_found")
        return res
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        if headers != expected_headers:
            res["errors"].append({"header_mismatch": {"got": headers, "expected": expected_headers}})
        count = 0
        dup_key_set: set[tuple[str, str, str]] = set()
        max_preview = 50
        # Flag de contrôle: priorité au paramètre explicite, sinon variable d'env
        env_strict = os.getenv("INDICATORS_CSV_SYMBOL_UPPER_STRICT", "1") == "1"
        strict_flag = env_strict if strict_symbol_upper is None else bool(strict_symbol_upper)
        for row in reader:
            count += 1
            # Basic schema checks
            ts = row.get("timestamp", "")
            dt = _parse_iso8601(ts)
            if (not dt) and (not lenient_timestamps):
                res["errors"].append({"bad_timestamp": ts})
            asset = row.get("asset", "")
            symbol = row.get("symbol", "")
            if not asset or not symbol:
                res["errors"].append({"missing_asset_or_symbol": row})
            if strict_flag and symbol and symbol.upper() != symbol:
                res["errors"].append({"symbol_not_upper": symbol})
            metric = row.get("metric_name", "")
            val_s = row.get("value", "")
            try:
                _ = float(val_s)
            except Exception:
                res["errors"].append({"non_numeric_value": val_s})
            # Duplicate key heuristic (ts, metric, symbol)
            key = (ts, metric, symbol)
            if key in dup_key_set:
                res["errors"].append({"duplicate_key": key})
            else:
                dup_key_set.add(key)
            if count >= max_preview and len(res["errors"]) < 1:
                # Stop early if preview ok and no error so far
                pass
        res["rows"] = count
    return res


def _find_db() -> Path | None:
    """Localise la base SQLite locale par heuristique (env -> défaut helper -> recherche récursive).

    Ordre:
        1) $BYBIT_WS_DB si fichier existant
        2) CRYPTO_DB_PATH / helper get_default_db_path()
        3) *.db le plus pertinent/récent sous data/

    Returns:
        Path | None: chemin DB si trouvé, sinon None.
    """
    # 1) Env override spécifique
    env_db = os.getenv("BYBIT_WS_DB")
    if env_db:
        candidate = Path(env_db)
        if candidate.exists():
            return candidate
    # 2) Helper central (respecte CRYPTO_DB_PATH)
    helper_raw = Path(get_default_db_path())
    helper_candidates = [helper_raw]
    if not helper_raw.is_absolute():
        helper_candidates.append((REPO_ROOT / helper_raw).resolve())
    for candidate in helper_candidates:
        if candidate.exists():
            return candidate
    # 3) Heuristic
    data_dir = REPO_ROOT / "data"
    dbs = list(data_dir.rglob("*.db")) if data_dir.exists() else []
    dbs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in dbs:
        if re.search(r"(bybit|liq)", p.name, re.I):
            return p
    return dbs[0] if dbs else None


def _validate_sqlite(db_path: Path, limit: int = 100) -> dict[str, Any]:
    """Contrôles minimaux sur la base SQLite (tables et échantillon de lignes).

    Args:
        db_path: chemin de la base SQLite
        limit: nombre de lignes à inspecter dans la table brute
    Returns:
        Détails: {db, exists, tables, errors, counts}
    """
    res: dict[str, Any] = {"db": str(db_path), "exists": db_path.exists(), "tables": [], "errors": [], "counts": {}}
    if not db_path.exists():
        res["errors"].append("db_not_found")
        return res
    conn = sqlite3.connect(db_path.as_posix())
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        res["tables"] = tables
        # Raw events table
        raw = next((t for t in tables if t == "bybit_liquidations" or re.search(r"liquidat", t, re.I)), None)
        if raw and _validate_table_name(raw):
            cur.execute(f"SELECT COUNT(1) FROM {raw}")
            count = int(cur.fetchone()[0])
            res["counts"][raw] = count
            # Sample validations
            cur.execute(f"PRAGMA table_info({raw})")
            cols = [r[1] for r in cur.fetchall()]
            required = {"symbol", "side", "price", "qty", "time"}
            missing = sorted(list(required - set(cols)))
            if missing:
                res["errors"].append({"raw_missing_columns": missing})
            cur.execute(f"SELECT symbol, side, price, qty, time FROM {raw} ORDER BY time DESC LIMIT ?", (limit,))
            bad_rows = 0
            for sym, side, price, qty, t in cur.fetchall():
                if not isinstance(sym, str) or sym.upper() != sym:
                    bad_rows += 1
                if side not in ("BUY", "SELL"):
                    bad_rows += 1
                if (price is None) or (float(price) <= 0):
                    bad_rows += 1
                if (qty is None) or (float(qty) < 0):
                    bad_rows += 1
                # time should be plausible (ms epoch)
                try:
                    if int(t) < 946684800000:  # before 2000-01-01 in ms epoch
                        bad_rows += 1
                except Exception:
                    bad_rows += 1
            if bad_rows:
                res["errors"].append({"raw_bad_rows": bad_rows})
        # Hourly aggregate
        hourly = next((t for t in tables if t == "bybit_liquidations_hourly"), None)
        if hourly and _validate_table_name(hourly):
            cur.execute(f"SELECT COUNT(1) FROM {hourly}")
            res["counts"][hourly] = int(cur.fetchone()[0])
    finally:
        conn.close()
    return res


def _encrypt_sensitive_files(recipient: str | None = None) -> dict[str, Any]:
    """Chiffre les fichiers sensibles (whales, liquidations) avec GPG.

    Args:
        recipient: Destinataire GPG (email ou fingerprint)

    Returns:
        Dict avec résultats du chiffrement
    """
    if not GPG_AVAILABLE:
        return {"error": "python-gnupg not available"}

    if not recipient:
        recipient = os.getenv("GPG_RECIPIENT")
        if not recipient:
            return {"error": "no GPG recipient specified"}

    result = {"encrypted_files": [], "errors": []}

    try:
        gpg = gnupg.GPG()
        gpg.encoding = 'utf-8'
    except Exception as e:
        return {"error": f"GPG initialization failed: {e}"}

    # Fichiers sensibles à chiffrer
    sensitive_files = [
        EXPORTS_DIR / "whales" / "whale_insider_snapshot.json",
        # Ajouter d'autres fichiers sensibles si nécessaire
    ]

    for file_path in sensitive_files:
        if not file_path.exists():
            continue

        try:
            # Lire le fichier original
            with file_path.open("rb") as f:
                data = f.read()

            # Chiffrer avec GPG
            encrypted_data = gpg.encrypt(data, recipients=[recipient])

            if not encrypted_data.ok:
                result["errors"].append(f"encryption failed for {file_path}: {encrypted_data.status}")
                continue

            # Écrire le fichier chiffré (remplace l'original)
            with file_path.open("wb") as f:
                f.write(encrypted_data.data)

            result["encrypted_files"].append(str(file_path))

        except Exception as e:
            result["errors"].append(f"failed to encrypt {file_path}: {e}")

    return result


def _render_html_report(path: Path, payload: dict[str, Any]) -> None:
    """Génère un rapport HTML statique à partir du payload JSON d'audit.

    Le HTML intègre des liens cliquables vers:
        - le fichier d'indicateurs (CSV/Parquet)
        - le JSON de rapport s'il est écrit à côté (json_report_path)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    status = str(payload.get("status", "")).upper()
    ok = status == "PASS"
    tag = payload.get("tag")
    tool_version = payload.get("tool_version") or TOOL_VERSION
    generated_at = payload.get("generated_at") or datetime.now(UTC).isoformat()
    indicators = payload.get("indicators", {})
    latest = indicators.get("latest", {}) if isinstance(indicators, dict) else {}
    rows = latest.get("rows", "-")
    nnr = latest.get("non_nan_ratio", "-")
    rsi = latest.get("rsi_in_bounds_ratio", "-")
    atr = latest.get("atr_nonneg_ratio", "-")
    stoch = latest.get("stoch_in_bounds_ratio", "-")
    bb = latest.get("bb_bounds_ratio", "-")
    sha_ok = latest.get("sha256_match", False)
    ind_path = latest.get("path", "-")
    # Build clickable link for indicator path if possible
    try:
        _p = Path(ind_path)
        ind_href = _p.resolve().as_uri() if _p.exists() or _p.is_absolute() else ind_path
    except Exception:
        ind_href = ind_path
    # Build clickable link for JSON report if available
    json_path_val = payload.get("json_report_path")
    json_link_html = ""
    if isinstance(json_path_val, str) and json_path_val:
        try:
            _jp = Path(json_path_val)
            json_href = _jp.resolve().as_uri() if _jp.exists() or _jp.is_absolute() else json_path_val
        except Exception:
            json_href = str(json_path_val)
        json_link_html = f'<p class="mono">JSON: <a href="{json_href}">{json_path_val}</a></p>'
    color = "#0a0" if ok else "#a00"

    # Quick issues summary
    def _first_n(items: list[Any], n: int = 3) -> list[Any]:
        try:
            return list(items[:n])
        except Exception:
            return []

    csv_latest = payload.get("csv_latest", {})
    csv_ts = payload.get("csv_timestamped", {})
    db = payload.get("db", {})
    ind = (payload.get("indicators", {}) or {}).get("latest", {})
    summary_blocks: list[str] = []
    for name, sect in (
        ("csv_latest", csv_latest),
        ("csv_timestamped", csv_ts),
        ("db", db),
        ("indicators", ind),
    ):
        if isinstance(sect, dict) and sect.get("errors"):
            errs = sect.get("errors") or []
            preview = _first_n(errs, 3)
            summary_blocks.append(
                f'<div><strong>{name}:</strong> {len(errs)} erreur(s)<pre class="mono">{json.dumps(preview, ensure_ascii=False, indent=2)}</pre></div>'
            )
    issues_html = "\n".join(summary_blocks) if summary_blocks else "<p>Aucune erreur majeure recensée.</p>"

    # Thresholds (prefer payload, fallback to env defaults)
    thr_payload = payload.get("thresholds") or {}

    def _thr(name: str, dv: float) -> float:
        try:
            if isinstance(thr_payload, dict) and name in thr_payload:
                return float(thr_payload[name])
        except Exception:
            pass
        try:
            return float(os.getenv(name, str(dv)))
        except Exception:
            return dv

    thr_nnr = _thr("INDICATORS_NON_NAN_MIN", 0.8)
    thr_rsi = _thr("INDICATORS_RSI_BOUNDS_MIN", 0.9)
    thr_atr = _thr("INDICATORS_ATR_NONNEG_MIN", 0.95)
    thr_stoch = _thr("INDICATORS_STOCH_BOUNDS_MIN", 0.9)
    thr_bb = _thr("INDICATORS_BB_BOUNDS_MIN", 0.95)
    warmup_rows = int(payload.get("warmup_rows", 50))

    # Useful resources/links section
    links_html = """
    <ul>
      <li><a href="../indicators/">exports/indicators</a></li>
      <li><a href="../../docs/INDICATORS_README.md">docs/INDICATORS_README.md</a></li>
    </ul>
    """

    html = f"""
<!DOCTYPE html>
<html lang=\"fr\">
<head>
    <meta charset=\"utf-8\" />
    <title>Audit Indicateurs — {status}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .status {{ font-weight: bold; color: {color}; }}
        table {{ border-collapse: collapse; margin-top: 10px; }}
        td, th {{ border: 1px solid #ddd; padding: 6px 10px; }}
        th {{ background: #f4f4f4; text-align: left; }}
        .mono {{ font-family: Consolas, monospace; }}
    </style>
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <meta http-equiv=\"X-UA-Compatible\" content=\"IE=edge\" />
    <meta name=\"robots\" content=\"noindex,nofollow\" />
    <meta name=\"generated\" content=\"{generated_at}\" />
    <meta name=\"tool_version\" content=\"{tool_version}\" />
    </head>
<body>
    <h1>Audit Indicateurs <span class=\"status\">{status}</span></h1>
    <p>Version outil: <strong>{tool_version}</strong>{' — Tag: <strong>' + str(tag) + '</strong>' if tag else ''} — Généré: <span class=\"mono\">{generated_at}</span></p>
    <p class=\"mono\">Fichier indicateurs: <a href=\"{ind_href}\">{ind_path}</a></p>
    {json_link_html}
    <table>
        <tr><th>Métrique</th><th>Valeur</th></tr>
        <tr><td>Rows</td><td>{rows}</td></tr>
        <tr><td>Non-NaN ratio</td><td>{nnr}</td></tr>
        <tr><td>RSI in [0,100]</td><td>{rsi}</td></tr>
        <tr><td>ATR ≥ 0</td><td>{atr}</td></tr>
        <tr><td>Stoch in [0,100]</td><td>{stoch}</td></tr>
        <tr><td>Bollinger BBL≤BBM≤BBU</td><td>{bb}</td></tr>
        <tr><td>SHA256 match</td><td>{sha_ok}</td></tr>
    </table>
    <p>Warmup: {warmup_rows} lignes ignorées au début. Seuils: non-NaN ≥ {thr_nnr}, RSI in-bounds ≥ {thr_rsi}, ATR non-négatif ≥ {thr_atr}, Stoch in-bounds ≥ {thr_stoch}, Bollinger bounds ≥ {thr_bb}</p>
    <h3>Problèmes détectés (résumé)</h3>
    {issues_html}
    <h3>Résumé JSON</h3>
    <pre class=\"mono\">{json.dumps(payload, indent=2)}</pre>
    <h3>How to reproduce (PowerShell)</h3>
    <pre class=\"mono\">& ".\\.venv\\Scripts\\python.exe" tools\\generate_indicators_csv.py --source synthetic --symbol BTCUSDT --interval 1h --limit 300 --out-format parquet --indicators rsi,ema,macd,bbands,atr,stoch,adx,cci,roc,obv,adl,kc
& ".\\.venv\\Scripts\\python.exe" tools\\data_quality_audit.py --html</pre>
    <h3>Ressources utiles</h3>
    {links_html}
</body>
</html>
"""
    with path.open("w", encoding="utf-8") as f:
        f.write(html)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit des exports core + indicateurs")
    parser.add_argument("--html", action="store_true", help="Générer un rapport HTML minimal")
    parser.add_argument(
        "--html-path",
        default=None,
        help="Chemin du rapport HTML (défaut: exports/indicators/report.html)",
    )
    parser.add_argument(
        "--report-name",
        default=None,
        help="Nom du rapport HTML (sans chemin, .html sera ajouté) si --html-path n'est pas fourni",
    )
    parser.add_argument(
        "--no-fail-exit",
        action="store_true",
        help="Toujours retourner le code de sortie 0 même si l'audit est en FAIL (observabilité)",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Chemin d'un fichier JSON à écrire avec le résultat de l'audit",
    )
    parser.add_argument(
        "--print-tips",
        action="store_true",
        help="Affiche des conseils rapides sur stderr (utile quand le statut est FAIL)",
    )
    parser.add_argument(
        "--tag",
        default=None,
        help="Tag libre (ex: env/profil) à inclure dans le rapport JSON/HTML",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Affiche la version de l'outil et quitte",
    )
    parser.add_argument(
        "--warmup-rows",
        type=int,
        default=None,
        help="Nombre de premières lignes à ignorer pour le calcul des ratios (défaut: 50 ou $INDICATORS_WARMUP_ROWS)",
    )
    parser.add_argument(
        "--skip-csv",
        action="store_true",
        help="Ignore la validation des CSV core (latest/timestamped)",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Ignore la validation de la base SQLite",
    )
    parser.add_argument(
        "--skip-indicators",
        action="store_true",
        help="Ignore la validation des indicateurs",
    )
    parser.add_argument(
        "--lenient-symbols",
        action="store_true",
        help="N'applique pas la contrainte d'uppercase strict sur les symboles CSV (équivalent INDICATORS_CSV_SYMBOL_UPPER_STRICT=0)",
    )
    parser.add_argument(
        "--lenient-timestamps",
        action="store_true",
        help="N'applique pas la contrainte de parsage strict sur les timestamps CSV",
    )
    parser.add_argument(
        "--encrypt-report",
        action="store_true",
        help="Chiffrer les fichiers sensibles (whales, liquidations) avec GPG avant génération du rapport",
    )
    parser.add_argument(
        "--gpg-recipient",
        default=None,
        help="Destinataire GPG pour le chiffrement (email ou fingerprint)",
    )
    args = parser.parse_args()

    if args.version:
        print(f"data_quality_audit {TOOL_VERSION}")
        return 0
    overall_ok = True
    summary: dict[str, Any] = {"csv": {}, "db": {}, "indicators": {}}

    # Déterminer la stricte uppercase effective pour les symboles CSV
    # Priorité drapeau CLI (--lenient-symbols) > variable d'env (INDICATORS_CSV_SYMBOL_UPPER_STRICT)
    try:
        env_strict_default = os.getenv("INDICATORS_CSV_SYMBOL_UPPER_STRICT", "1") == "1"
    except Exception:
        env_strict_default = True
    csv_symbol_upper_strict = False if args.lenient_symbols else env_strict_default

    # CSV: resolve latest export from manifest, fallback to exports/latest_export.csv
    expected_headers = [
        "timestamp",
        "asset",
        "symbol",
        "chain",
        "metric_name",
        "value",
        "source",
        "confidence_score",
    ]
    mani = _read_latest_manifest()
    latest_path: Path | None = None
    ts_path: Path | None = None
    row_count_manifest: int | None = None
    sha_manifest: str | None = None

    if mani and isinstance(mani, dict):
        latest = mani.get("latest_path")
        ts = mani.get("timestamped_path")
        row_count_manifest = mani.get("row_count")
        sha_manifest = mani.get("sha256")
        if latest:
            latest_path = (REPO_ROOT / latest).resolve() if not os.path.isabs(latest) else Path(latest)
        if ts:
            ts_path = (REPO_ROOT / ts).resolve() if not os.path.isabs(ts) else Path(ts)

    if not latest_path:
        fallback = EXPORTS_DIR / "latest_export.csv"
        if fallback.exists():
            latest_path = fallback

    csv_latest_res: dict[str, Any] | None = None
    csv_ts_res: dict[str, Any] | None = None

    if args.skip_csv:
        summary["csv_latest"] = {"skipped": True}
        summary["csv_timestamped"] = {"skipped": True}
    else:
        if latest_path:
            csv_latest_res = _validate_csv(
                latest_path,
                expected_headers,
                strict_symbol_upper=csv_symbol_upper_strict,
                lenient_timestamps=args.lenient_timestamps,
            )
            # Optionnel: vérifier cohérence row_count du manifest
            if (row_count_manifest is not None) and (csv_latest_res.get("rows", 0) != row_count_manifest):
                csv_latest_res.setdefault("errors", []).append(
                    {"row_count_mismatch": {"got": csv_latest_res.get("rows"), "manifest": row_count_manifest}}
                )
            summary["csv_latest"] = csv_latest_res
            if csv_latest_res.get("errors"):
                overall_ok = False
        else:
            summary["csv_latest"] = {"error": "no_latest_csv_found"}
            overall_ok = False

    if not args.skip_csv:
        if ts_path:
            csv_ts_res = _validate_csv(
                ts_path,
                expected_headers,
                strict_symbol_upper=csv_symbol_upper_strict,
                lenient_timestamps=args.lenient_timestamps,
            )
            # Vérifier sha256 du timestamped (le manifest référence ce fichier)
            if sha_manifest:
                sha_ok = _sha256_file(ts_path) == sha_manifest
                csv_ts_res["sha256_match"] = sha_ok
                if not sha_ok:
                    csv_ts_res.setdefault("errors", []).append("sha256_mismatch")
            # Vérifier cohérence row_count
            if (row_count_manifest is not None) and (csv_ts_res.get("rows", 0) != row_count_manifest):
                csv_ts_res.setdefault("errors", []).append(
                    {"row_count_mismatch": {"got": csv_ts_res.get("rows"), "manifest": row_count_manifest}}
                )
            summary["csv_timestamped"] = csv_ts_res
            if csv_ts_res.get("errors"):
                overall_ok = False
        else:
            summary["csv_timestamped"] = {"error": "no_timestamped_csv_found"}
            # Si pas de ts_path, on ne peut pas valider le sha du manifest

    # DB: find and validate
    if args.skip_db:
        summary["db"] = {"skipped": True}
    else:
        db = _find_db()
        if db:
            db_res = _validate_sqlite(db)
            summary["db"] = db_res
            if db_res.get("errors"):
                overall_ok = False
        else:
            summary["db"] = {"error": "no_db_found"}
            overall_ok = False

    # Warmup rows and thresholds
    try:
        env_warmup = int(os.getenv("INDICATORS_WARMUP_ROWS", "50"))
    except Exception:
        env_warmup = 50
    warmup_rows = args.warmup_rows if args.warmup_rows is not None else env_warmup

    def _thr_parse(name: str, dv: float) -> float:
        try:
            return float(os.getenv(name, str(dv)))
        except Exception:
            return dv

    thresholds = {
        "INDICATORS_NON_NAN_MIN": _thr_parse("INDICATORS_NON_NAN_MIN", 0.8),
        "INDICATORS_RSI_BOUNDS_MIN": _thr_parse("INDICATORS_RSI_BOUNDS_MIN", 0.9),
        "INDICATORS_ATR_NONNEG_MIN": _thr_parse("INDICATORS_ATR_NONNEG_MIN", 0.95),
        "INDICATORS_STOCH_BOUNDS_MIN": _thr_parse("INDICATORS_STOCH_BOUNDS_MIN", 0.9),
        "INDICATORS_BB_BOUNDS_MIN": _thr_parse("INDICATORS_BB_BOUNDS_MIN", 0.95),
    }

    # Indicators CSV (facultatif, mais si présent on valide un minimum)
    ind_mani = _read_latest_indicators_manifest()
    if args.skip_indicators:
        summary["indicators"] = {"skipped": True}
    elif ind_mani:
        ind_path = Path(ind_mani.get("path", ""))
        if not ind_path.is_absolute():
            ind_path = (REPO_ROOT / ind_path).resolve()
        ind_sha = ind_mani.get("sha256")
        _ = ind_mani.get("columns") or []  # unused metadata, kept for completeness
        ind_fmt = str(ind_mani.get("format", "csv")).lower()
        res_ind: dict[str, Any] = {"path": ind_path.as_posix(), "exists": ind_path.exists(), "errors": []}
        if ind_path.exists():
            # Lecture rapide et vérif basique: au moins 50% des colonnes indicateurs non-NaN après warmup
            try:
                import pandas as _pd
            except ImportError:
                res_ind["errors"].append({"pandas_import_error": "pandas not available"})
                df = None
            else:
                if ind_fmt == "parquet":
                    try:
                        df = _pd.read_parquet(ind_path)
                    except Exception as e:
                        res_ind["errors"].append({"parquet_read_error": str(e)})
                        df = _pd.DataFrame()
                else:
                    df = _pd.read_csv(ind_path)
                # Colonnes indicateurs = toutes sauf timestamp et OHLC de base si présents
                base_cols = {"timestamp", "open", "high", "low", "close", "volume"}
                ind_only = [c for c in df.columns if c not in base_cols]
                # Warmup: drop les premières lignes si dispo
                df_work = df.iloc[warmup_rows:] if df.shape[0] > warmup_rows else df
                non_nan_ratio = float(df_work[ind_only].notna().mean().mean()) if ind_only else 1.0
                res_ind["rows"] = int(df.shape[0])
                res_ind["non_nan_ratio"] = non_nan_ratio
                # Vérification bornes RSI (si présent): ratio des valeurs dans [0,100] après warmup
                if "RSI" in df_work.columns:
                    rsi_series = df_work["RSI"]
                    with contextlib.suppress(Exception):
                        valid = ((rsi_series >= 0.0) & (rsi_series <= 100.0)) & rsi_series.notna()
                        denom = int(rsi_series.notna().sum())
                        if denom > 0:
                            rsi_ratio = float(valid.sum()) / float(denom)
                            res_ind["rsi_in_bounds_ratio"] = rsi_ratio
                            rsi_thr = float(thresholds["INDICATORS_RSI_BOUNDS_MIN"])
                            if rsi_ratio < rsi_thr:
                                res_ind.setdefault("errors", []).append({"rsi_bounds_low_ratio": rsi_ratio})
                # Vérification ATR non-négatif (si présent)
                if "ATR" in df_work.columns:
                    atr_series = df_work["ATR"]
                    with contextlib.suppress(Exception):
                        denom = int(atr_series.notna().sum())
                        if denom > 0:
                            atr_valid = ((atr_series >= 0.0) & atr_series.notna()).sum()
                            atr_ratio = float(atr_valid) / float(denom)
                            res_ind["atr_nonneg_ratio"] = atr_ratio
                            atr_thr = float(thresholds["INDICATORS_ATR_NONNEG_MIN"])
                            if atr_ratio < atr_thr:
                                res_ind.setdefault("errors", []).append({"atr_nonneg_low_ratio": atr_ratio})
                # Vérification Stochastique (%K/%D) dans [0,100] (si présent)
                try:
                    # Exclure l'histogramme (souvent suffixe 'h') qui n'est pas borné [0,100]
                    stoch_cols = [
                        c for c in df_work.columns if c.upper().startswith("STOCH") and not c.upper().startswith("STOCHH")
                    ]
                except Exception:
                    stoch_cols = []
                if stoch_cols:
                    ratios: list[float] = []
                    for col in stoch_cols:
                        s = df_work[col]
                        with contextlib.suppress(Exception):
                            denom = int(s.notna().sum())
                            if denom > 0:
                                valid_flags = ((s >= 0.0) & (s <= 100.0) & s.notna()).tolist()
                                valid_count = sum(1 for flag in valid_flags if bool(flag))
                                ratios.append(float(valid_count) / float(denom))
                    if ratios:
                        stoch_ratio = float(sum(ratios) / len(ratios))
                        res_ind["stoch_in_bounds_ratio"] = stoch_ratio
                        stoch_thr = float(thresholds["INDICATORS_STOCH_BOUNDS_MIN"])
                        if stoch_ratio < stoch_thr:
                            res_ind.setdefault("errors", []).append({"stoch_bounds_low_ratio": stoch_ratio})

                # Vérification Bollinger (si présentes): BBL <= BBM <= BBU
                try:
                    bbl_cols = [c for c in df_work.columns if c.upper().startswith("BBL_")]
                except Exception:
                    bbl_cols = []
                bb_ratios: list[float] = []
                for bbl in bbl_cols:
                    suffix = bbl.split("BBL_", 1)[1] if "BBL_" in bbl else ""
                    bbm = f"BBM_{suffix}" if suffix else None
                    bbu = f"BBU_{suffix}" if suffix else None
                    if bbm in df_work.columns and bbu in df_work.columns:
                        b1 = df_work[bbl]
                        b2 = df_work[bbm]
                        b3 = df_work[bbu]
                        mask = b1.notna() & b2.notna() & b3.notna()
                        denom = int(mask.sum())
                        if denom > 0:
                            valid_flags = ((b1 <= b2) & (b2 <= b3) & mask).tolist()
                            valid_count = sum(1 for flag in valid_flags if bool(flag))
                            bb_ratios.append(float(valid_count) / float(denom))
                if bb_ratios:
                    bb_ratio = float(sum(bb_ratios) / len(bb_ratios))
                    res_ind["bb_bounds_ratio"] = bb_ratio
                    bb_thr = float(thresholds["INDICATORS_BB_BOUNDS_MIN"])
                    if bb_ratio < bb_thr:
                        res_ind.setdefault("errors", []).append({"bb_bounds_low_ratio": bb_ratio})
                if ind_sha:
                    res_ind["sha256_match"] = _sha256_file(ind_path) == ind_sha
                    if not res_ind["sha256_match"]:
                        res_ind["errors"].append("sha256_mismatch")
                _threshold = float(thresholds["INDICATORS_NON_NAN_MIN"])
                if non_nan_ratio < _threshold:  # exige au moins 80% (par défaut) de non-NaN après warmup
                    res_ind["errors"].append({"low_non_nan_ratio": non_nan_ratio})
        else:
            res_ind["errors"].append("indicators_csv_not_found")
        summary["indicators"]["latest"] = res_ind
        if res_ind.get("errors"):
            overall_ok = False

    status = "PASS" if overall_ok else "FAIL"
    payload = {"status": status, **summary}
    payload["thresholds"] = thresholds
    payload["warmup_rows"] = warmup_rows
    payload["generated_at"] = datetime.now(UTC).isoformat()
    payload["tool_version"] = TOOL_VERSION
    payload["csv_symbol_upper_strict"] = csv_symbol_upper_strict
    if args.tag:
        payload["tag"] = args.tag
    if args.no_fail_exit:
        payload["no_fail_exit"] = True

    # Chiffrement des fichiers sensibles si demandé
    if args.encrypt_report:
        encrypt_result = _encrypt_sensitive_files(args.gpg_recipient)
        payload["encryption"] = encrypt_result
        if encrypt_result.get("error"):
            print(f"Encryption warning: {encrypt_result['error']}", file=sys.stderr)
        elif encrypt_result.get("encrypted_files"):
            print(f"Encrypted {len(encrypt_result['encrypted_files'])} sensitive files", file=sys.stderr)

    # Rapport HTML optionnel (flag ou env)
    want_html = args.html or os.getenv("INDICATORS_AUDIT_HTML", "0") == "1"
    html_path: Path | None = None
    if want_html:
        html_path_env = os.getenv("INDICATORS_AUDIT_HTML_PATH")
        if args.html_path:
            html_path = Path(args.html_path)
        elif html_path_env:
            html_path = Path(html_path_env)
        elif args.report_name:
            name = args.report_name
            if not name.lower().endswith(".html"):
                name = f"{name}.html"
            html_path = EXPORTS_DIR / "indicators" / name
        else:
            html_path = EXPORTS_DIR / "indicators" / "report.html"
        # Expose la cible HTML dans le payload avant rendu (pour lien et debug)
        if html_path is not None:
            payload["html_report_path"] = html_path.as_posix()

    # Écriture JSON optionnelle (fichier dédié ou sidecar par défaut si demandé via env)
    if args.json_out:
        try:
            out_path = Path(args.json_out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Expose the json path in payload before writing the file
            payload["json_report_path"] = out_path.as_posix()
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            # Don't crash on write error; continue
            pass
    elif want_html and os.getenv("INDICATORS_AUDIT_JSON_DEFAULT", "0") == "1":
        # Write default JSON next to HTML report when requested via env
        try:
            default_json = EXPORTS_DIR / "indicators" / "report.json"
            default_json.parent.mkdir(parents=True, exist_ok=True)
            payload["json_report_path"] = default_json.as_posix()
            with default_json.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass

    # Générer le HTML après avoir potentiellement écrit payload[json_report_path]
    # pour permettre un lien depuis l'HTML vers le JSON sidecar.
    if want_html and html_path is not None:
        with contextlib.suppress(Exception):
            _render_html_report(html_path, payload)
        print(f"HTML report: {html_path}", file=sys.stderr)

    # Optional quick tips to stderr to help users when things fail
    if args.print_tips or (payload.get("status") == "FAIL"):
        try:
            tips: list[str] = []
            tips.append("Conseils rapides:")
            tips.append(
                "- Vérifiez les seuils via env: INDICATORS_NON_NAN_MIN, INDICATORS_RSI_BOUNDS_MIN, INDICATORS_ATR_NONNEG_MIN, INDICATORS_STOCH_BOUNDS_MIN, INDICATORS_BB_BOUNDS_MIN"
            )
            tips.append("- Pour un run local stable: générez un set synthétique puis auditez:")
            tips.append(
                '  & ".\\.venv\\Scripts\\python.exe" tools\\generate_indicators_csv.py --source synthetic --symbol BTCUSDT --interval 1h --limit 300 --indicators rsi,ema,macd,bbands,atr,stoch,adx,cci,roc,obv,adl,kc'
            )
            tips.append('  & ".\\.venv\\Scripts\\python.exe" tools\\data_quality_audit.py --html')
            tips.append("- En CI d'observabilité, utilisez --no-fail-exit pour ne pas bloquer les jobs si status=FAIL")
            tips.append(
                '- Pour écrire automatiquement un JSON à côté du HTML: $env:INDICATORS_AUDIT_JSON_DEFAULT = "1"'
            )
            tips.append(
                "- Si vos CSV ont des symboles en minuscule: ajoutez --lenient-symbols (ou INDICATORS_CSV_SYMBOL_UPPER_STRICT=0)"
            )
            print("\n".join(tips), file=sys.stderr)
        except Exception:
            pass

    print(json.dumps(payload, indent=2))

    return 0 if (overall_ok or args.no_fail_exit) else 1


if __name__ == "__main__":
    raise SystemExit(main())

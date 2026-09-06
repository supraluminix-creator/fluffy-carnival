from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2

import pandas as pd


def _write_minimal_core_csvs(repo: Path) -> None:
    exports = repo / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    # latest_export.csv
    latest = exports / "latest_export.csv"
    rows = [
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "asset": "BTC",
            "symbol": "BTCUSDT",
            "chain": "-",
            "metric_name": "demo",
            "value": "1.0",
            "source": "test",
            "confidence_score": "1.0",
        },
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "asset": "ETH",
            "symbol": "ETHUSDT",
            "chain": "-",
            "metric_name": "demo",
            "value": "2.0",
            "source": "test",
            "confidence_score": "1.0",
        },
    ]
    cols = [
        "timestamp",
        "asset",
        "symbol",
        "chain",
        "metric_name",
        "value",
        "source",
        "confidence_score",
    ]
    with latest.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # timestamped CSV + manifest
    ts_name = f"pipeline_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    ts_path = exports / ts_name
    with ts_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # write export_manifest.jsonl
    sha = _sha256(ts_path)
    mani = {
        "latest_path": latest.as_posix(),
        "timestamped_path": ts_path.as_posix(),
        "row_count": len(rows),
        "sha256": sha,
    }
    with (exports / "export_manifest.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(mani) + "\n")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_minimal_db(repo: Path) -> None:
    data_dir = repo / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "crypto.db"
    conn = sqlite3.connect(db_path.as_posix())
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS bybit_liquidations (id INTEGER PRIMARY KEY, symbol TEXT, side TEXT, price REAL, qty REAL, time INTEGER)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS bybit_liquidations_hourly (id INTEGER PRIMARY KEY, hour TEXT, count INTEGER)"
    )
    # Insert a couple of plausible rows
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    cur.execute(
        "INSERT INTO bybit_liquidations (symbol, side, price, qty, time) VALUES (?,?,?,?,?)",
        ("BTCUSDT", "BUY", 50000.0, 1.23, now_ms),
    )
    cur.execute(
        "INSERT INTO bybit_liquidations_hourly (hour, count) VALUES (?,?)",
        (datetime.now(UTC).strftime("%Y-%m-%dT%H"), 1),
    )
    conn.commit()
    conn.close()


def _write_minimal_indicators(repo: Path) -> Path:
    out_dir = repo / "exports" / "indicators"
    out_dir.mkdir(parents=True, exist_ok=True)
    # tiny DataFrame with required columns
    df = pd.DataFrame(
        {
            "timestamp": [datetime.now(UTC).isoformat()] * 100,
            "open": [1.0] * 100,
            "high": [2.0] * 100,
            "low": [0.5] * 100,
            "close": [1.5] * 100,
            "volume": [10.0] * 100,
            "RSI": [50.0] * 100,
            "ATR": [0.1] * 100,
            "STOCHk": [20.0] * 100,
            "STOCHd": [30.0] * 100,
            "BBL_20_2.0": [1.0] * 100,
            "BBM_20_2.0": [1.3] * 100,
            "BBU_20_2.0": [1.6] * 100,
        }
    )
    ind_path = out_dir / "ind_test_min.csv"
    df.to_csv(ind_path, index=False)
    sha = _sha256(ind_path)
    mani = {
        "path": ind_path.as_posix(),
        "row_count": int(df.shape[0]),
        "columns": list(df.columns),
        "sha256": sha,
        "format": "csv",
    }
    with (out_dir / "indicators_manifest.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(mani) + "\n")
    return ind_path


def test_audit_generates_html_report(tmp_path: Path, monkeypatch):
    # Arrange minimal repo structure in tmp dir
    repo = tmp_path
    (repo / "exports").mkdir(parents=True, exist_ok=True)
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    # Point REPO_ROOT env to tmp repo by adjusting cwd when calling script
    # But our audit uses Path(__file__).parent.parent, so we copy the script in place
    project_root = Path(__file__).resolve().parents[1]
    script_src = project_root / "tools" / "data_quality_audit.py"
    tools_dir = repo / "tools"
    copy2(script_src, tools_dir / "data_quality_audit.py")

    # Core CSVs and manifest
    _write_minimal_core_csvs(repo)
    # Minimal DB
    _write_minimal_db(repo)
    # Minimal indicators + manifest
    _write_minimal_indicators(repo)

    # Act: run audit with --html in this temp repo cwd
    cmd = [sys.executable, str(tools_dir / "data_quality_audit.py"), "--html", "--skip-indicators", "--no-fail-exit"]
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=False)
    assert proc.returncode in (0, 1)
    # Parse stdout JSON
    assert proc.stdout, f"Empty stdout, stderr: {proc.stderr}"
    payload = json.loads(proc.stdout)
    # Should at least produce HTML report regardless of PASS/FAIL here
    report = repo / "exports" / "indicators" / "report.html"
    assert report.exists(), proc.stderr
    assert report.stat().st_size > 0
    # The JSON payload should expose the report path when --html is used
    assert payload.get("html_report_path")
    # With our well-formed data and skips, should PASS
    assert payload.get("status") == "PASS"


def test_audit_no_fail_exit_even_on_fail(tmp_path: Path):
    # Arrange temp repo
    repo = tmp_path
    (repo / "exports").mkdir(parents=True, exist_ok=True)
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parents[1]
    copy2(project_root / "tools" / "data_quality_audit.py", repo / "tools" / "data_quality_audit.py")

    # Minimal core artifacts
    _write_minimal_core_csvs(repo)
    _write_minimal_db(repo)

    # Indicators with invalid RSI to trigger FAIL
    out_dir = repo / "exports" / "indicators"
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        {
            "timestamp": [datetime.now(UTC).isoformat()] * 100,
            "open": [1.0] * 100,
            "high": [2.0] * 100,
            "low": [0.5] * 100,
            "close": [1.5] * 100,
            "volume": [10.0] * 100,
            "RSI": [150.0] * 100,  # out of bounds to force failure
        }
    )
    ind_path = out_dir / "ind_fail.csv"
    df.to_csv(ind_path, index=False)
    sha = _sha256(ind_path)
    mani = {
        "path": ind_path.as_posix(),
        "row_count": int(df.shape[0]),
        "columns": list(df.columns),
        "sha256": sha,
        "format": "csv",
    }
    with (out_dir / "indicators_manifest.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(mani) + "\n")

    cmd = [sys.executable, str(repo / "tools" / "data_quality_audit.py"), "--html", "--no-fail-exit"]
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    # Should not fail thanks to --no-fail-exit
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload.get("status") == "FAIL"
    assert payload.get("no_fail_exit") is True
    assert (repo / "exports" / "indicators" / "report.html").exists()


def test_audit_json_out_includes_path_and_writes_file(tmp_path: Path):
    # Arrange temp repo
    repo = tmp_path
    (repo / "exports").mkdir(parents=True, exist_ok=True)
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parents[1]
    copy2(project_root / "tools" / "data_quality_audit.py", repo / "tools" / "data_quality_audit.py")

    # Minimal core artifacts and indicators
    _write_minimal_core_csvs(repo)
    _write_minimal_db(repo)
    _write_minimal_indicators(repo)

    # Act: run with --html and --json-out
    json_out = repo / "exports" / "indicators" / "audit.json"
    cmd = [sys.executable, str(repo / "tools" / "data_quality_audit.py"), "--html", "--json-out", str(json_out)]
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stderr
    payload = json.loads(proc.stdout)
    # Should include json_report_path and file should exist
    assert payload.get("json_report_path"), proc.stdout
    assert Path(payload["json_report_path"]).exists()
    # The written file should contain valid JSON with a status field
    written = json.loads(json_out.read_text(encoding="utf-8"))
    assert written.get("status") in ("PASS", "FAIL")
    # HTML should include a link or mention of the JSON path
    html_path = repo / "exports" / "indicators" / "report.html"
    assert html_path.exists()
    html_text = html_path.read_text(encoding="utf-8")
    assert str(json_out).replace("\\", "/") in html_text or str(json_out) in html_text


def test_audit_print_tips_emits_help_on_stderr(tmp_path: Path):
    repo = tmp_path
    (repo / "exports").mkdir(parents=True, exist_ok=True)
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parents[1]
    copy2(project_root / "tools" / "data_quality_audit.py", repo / "tools" / "data_quality_audit.py")

    _write_minimal_core_csvs(repo)
    _write_minimal_db(repo)
    _write_minimal_indicators(repo)

    cmd = [sys.executable, str(repo / "tools" / "data_quality_audit.py"), "--html", "--print-tips"]
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    assert proc.returncode in (0, 1)
    # Should contain the word 'Conseils rapides' in stderr
    assert "Conseils rapides" in (proc.stderr or "")


def test_audit_html_writes_default_json_sidecar_when_env_enabled(tmp_path: Path, monkeypatch):
    repo = tmp_path
    (repo / "exports").mkdir(parents=True, exist_ok=True)
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parents[1]
    copy2(project_root / "tools" / "data_quality_audit.py", repo / "tools" / "data_quality_audit.py")

    _write_minimal_core_csvs(repo)
    _write_minimal_db(repo)
    _write_minimal_indicators(repo)

    env = os.environ.copy()
    env["INDICATORS_AUDIT_JSON_DEFAULT"] = "1"
    cmd = [sys.executable, str(repo / "tools" / "data_quality_audit.py"), "--html"]
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, env=env)
    assert proc.returncode in (0, 1), proc.stderr
    payload = json.loads(proc.stdout)
    # default JSON should be exports/indicators/report.json
    default_json = repo / "exports" / "indicators" / "report.json"
    assert default_json.exists(), proc.stderr
    assert payload.get("json_report_path")
    # HTML exists and likely references the JSON path (best-effort)
    html_path = repo / "exports" / "indicators" / "report.html"
    assert html_path.exists()
    html_text = html_path.read_text(encoding="utf-8")
    assert str(default_json).replace("\\", "/") in html_text or str(default_json) in html_text

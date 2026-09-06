from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_core_csvs_and_manifest(repo: Path) -> None:
    exports = repo / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    headers = [
        "timestamp",
        "asset",
        "symbol",
        "chain",
        "metric_name",
        "value",
        "source",
        "confidence_score",
    ]
    rows = [
        {
            "timestamp": "2025-10-05T00:00:00Z",
            "asset": "btc",
            "symbol": "btcusdt",  # lower-case intentionally
            "chain": "-",
            "metric_name": "price",
            "value": "60000",
            "source": "test",
            "confidence_score": "1.0",
        }
    ]
    latest = exports / "latest_export.csv"
    with latest.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    ts = exports / "pipeline_export_20251005_000000.csv"
    with ts.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    mani = {
        "latest_path": latest.as_posix(),
        "timestamped_path": ts.as_posix(),
        "row_count": 1,
        "sha256": _sha256(ts),
    }
    with (exports / "export_manifest.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(mani) + "\n")


def test_lenient_symbols_flag_suppresses_uppercase_error(tmp_path: Path) -> None:
    # Prepare isolated temp repo: copy script and write minimal CSV artifacts
    repo = tmp_path
    tools_dir = repo / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    from shutil import copy2

    project_root = Path(__file__).resolve().parents[1]
    copy2(project_root / "tools" / "data_quality_audit.py", tools_dir / "data_quality_audit.py")

    _write_core_csvs_and_manifest(repo)

    env = os.environ.copy()
    env.pop("INDICATORS_CSV_SYMBOL_UPPER_STRICT", None)

    # Run strict (default): expect symbol_not_upper present
    proc_strict = subprocess.run(
        [
            sys.executable,
            os.fspath(tools_dir / "data_quality_audit.py"),
            "--skip-db",
            "--skip-indicators",
        ],
        cwd=os.fspath(repo),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc_strict.stdout, proc_strict.stderr
    data_strict = json.loads(proc_strict.stdout)
    errs_latest = (data_strict.get("csv_latest") or {}).get("errors") or []
    errs_ts = (data_strict.get("csv_timestamped") or {}).get("errors") or []
    assert any(
        "symbol_not_upper" in (e if isinstance(e, str) else next(iter(e.keys()), "")) for e in errs_latest + errs_ts
    )

    # Run with --lenient-symbols: expect no symbol_not_upper
    proc_len = subprocess.run(
        [
            sys.executable,
            os.fspath(tools_dir / "data_quality_audit.py"),
            "--skip-db",
            "--skip-indicators",
            "--lenient-symbols",
        ],
        cwd=os.fspath(repo),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    data_len = json.loads(proc_len.stdout)
    errs_latest_len = (data_len.get("csv_latest") or {}).get("errors") or []
    errs_ts_len = (data_len.get("csv_timestamped") or {}).get("errors") or []
    assert not any(
        "symbol_not_upper" in (e if isinstance(e, str) else next(iter(e.keys()), ""))
        for e in errs_latest_len + errs_ts_len
    )

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from shutil import copy2


def test_open_latest_html_dry_run(tmp_path: Path) -> None:
    # Prepare isolated repo with a fake HTML report
    repo = tmp_path
    tools_dir = repo / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parents[1]
    copy2(project_root / "tools" / "open_latest_indicators_report.py", tools_dir / "open_latest_indicators_report.py")

    html = repo / "exports" / "indicators" / "report.html"
    html.parent.mkdir(parents=True, exist_ok=True)
    html.write_text("<html><body>ok</body></html>", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            os.fspath(tools_dir / "open_latest_indicators_report.py"),
            "--dry-run",
        ],
        cwd=os.fspath(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Opened:" in proc.stdout and str(html) in proc.stdout


def test_open_latest_json_dry_run_with_env_override(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path
    tools_dir = repo / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parents[1]
    copy2(project_root / "tools" / "open_latest_indicators_report.py", tools_dir / "open_latest_indicators_report.py")

    # Create a JSON report at a custom path and point env to it
    custom_json = repo / "exports" / "indicators" / "custom.json"
    custom_json.parent.mkdir(parents=True, exist_ok=True)
    custom_json.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

    env = os.environ.copy()
    env["INDICATORS_AUDIT_JSON_PATH"] = str(custom_json)

    proc = subprocess.run(
        [
            sys.executable,
            os.fspath(tools_dir / "open_latest_indicators_report.py"),
            "--json",
            "--dry-run",
        ],
        cwd=os.fspath(repo),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Opened:" in proc.stdout and str(custom_json) in proc.stdout

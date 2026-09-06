from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from shutil import copy2


def test_dump_cmc_cycle_indicators_writes_json_and_manifest(tmp_path: Path, monkeypatch) -> None:
    # Arrange: isolated repo layout
    repo = tmp_path
    tools_dir = repo / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (repo / "pipeline" / "collectors").mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parents[1]

    # Copy modules into temp repo
    copy2(project_root / "tools" / "dump_cmc_cycle_indicators.py", tools_dir / "dump_cmc_cycle_indicators.py")
    copy2(
        project_root / "pipeline" / "collectors" / "coinmarketcap_cycle.py",
        repo / "pipeline" / "collectors" / "coinmarketcap_cycle.py",
    )

    # Make temp repo importable
    sys.path.insert(0, os.fspath(repo))
    try:
        # Import the CLI module we just copied (so its REPO_ROOT points to tmp repo)
        cli_mod = importlib.import_module("tools.dump_cmc_cycle_indicators")

        # Patch the fetch function to avoid network
        fake_items = [
            {
                "indicator": "Puell Multiple",
                "status": "undervalued",
                "value": 0.47,
                "thresholds": {"low": 0.5},
                "source": "api",
            }
        ]
        from pipeline.collectors import coinmarketcap_cycle as cmc_mod

        # Patch both the source module and the imported symbol inside the CLI module
        monkeypatch.setattr(cmc_mod, "fetch_cmc_cycle_indicators", lambda *a, **k: fake_items, raising=True)
        monkeypatch.setattr(cli_mod, "fetch_cmc_cycle_indicators", lambda *a, **k: fake_items, raising=True)

        # Simulate CLI args and run main()
        out_json = repo / "exports" / "cmc_cycle_indicators.json"
        monkeypatch.setenv("CMC_CYCLE_CACHE_DISABLE", "1")
        # Adjust argv for argparse in main()
        old_argv = sys.argv[:]
        sys.argv = [
            "dump_cmc_cycle_indicators.py",
            "--format",
            "json",
            "--out",
            os.fspath(out_json),
        ]
        try:
            rc = cli_mod.main()
        finally:
            sys.argv = old_argv
        assert rc == 0
        assert out_json.exists(), "JSON file not created"
        data = json.loads(out_json.read_text(encoding="utf-8"))
        assert data["count"] == 1

        mani_path = repo / "exports" / "indicators" / "cmc_cycle_manifest.jsonl"
        assert mani_path.exists(), "Manifest not created"
        lines = [ln.strip() for ln in mani_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert lines, "Manifest empty"
        last = json.loads(lines[-1])
        assert last.get("format") == "json"
        assert last.get("count") == 1
        assert Path(last.get("path", "")).resolve() == out_json.resolve()
    finally:
        # Clean sys.path
        if sys.path and sys.path[0] == os.fspath(repo):
            sys.path.pop(0)

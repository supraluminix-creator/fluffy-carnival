import importlib
import importlib.util
import json
import os
import pathlib

import pytest

# Le dossier "analysis/run_2025-09-20" contient un tiret qui empêche l'import direct classique.
# On résout dynamiquement le module via importlib.machinery.SourceFileLoader.
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
WS_SESSION_PATH = BASE_DIR / "analysis" / "run_2025-09-20" / "run_ws_session.py"
if not WS_SESSION_PATH.exists():
    raise RuntimeError(f"run_ws_session.py introuvable: {WS_SESSION_PATH}")

spec_name = "analysis.run_2025_09_20.run_ws_session"
spec = importlib.util.spec_from_file_location(spec_name, WS_SESSION_PATH)
module = importlib.util.module_from_spec(spec)  # type: ignore
assert spec and spec.loader
spec.loader.exec_module(module)  # type: ignore
run_ws_session = module.run_ws_session  # type: ignore[attr-defined]

FIXTURE_FILE = "analysis/run_2025-09-20/fixtures/ws_inject.jsonl"
ARTIFACT_DIR = "analysis/run_2025-09-20/artifacts"

@pytest.mark.asyncio
async def test_ws_injection_autostop():
    summary = await run_ws_session(
        mode="inject",
        symbols=["BTCUSDT", "ETHUSDT"],
        injection_file=FIXTURE_FILE,
    )
    # Basic assertions
    assert summary["mode"] == "inject"
    assert summary["events_per_symbol"].get("BTCUSDT") == 1
    assert summary["events_per_symbol"].get("ETHUSDT") == 1
    assert summary["connections_total"] >= 1  # simulated increment
    # Artifact presence
    artifact_path = os.path.join(ARTIFACT_DIR, "ws_session_summary_inject.json")
    assert os.path.exists(artifact_path)
    with open(artifact_path, encoding="utf-8") as f:
        persisted = json.load(f)
    assert persisted["events_per_symbol"] == summary["events_per_symbol"]

#!/usr/bin/env python3
"""CLI minimal pour lancer une analyse AI à la demande.

Usage (PowerShell):
  .\.venv\\Scripts\\python.exe cli_analysis.py

Variables d'environnement utiles:
  ANALYSIS_ONLY_ON_SIGNALS=1   # ne persiste que s'il y a des signaux
  OPENAI_API_KEY / OPENROUTER_API_KEY / OLLAMA_HOST pour providers
"""
from __future__ import annotations

import os

from pipeline.analysis.persist import save_analysis
from pipeline.analysis.runner import run_automatic_analyses


def main() -> None:
    export_path = os.path.join("exports", "latest_export.csv")
    out = run_automatic_analyses(export_path)
    only_on_signals = os.getenv("ANALYSIS_ONLY_ON_SIGNALS", "0") == "1"
    if (not only_on_signals) or out.get("signals"):
        save_analysis(out, "exports")
    print("analysis_status=", out.get("status"))
    if out.get("signals"):
        print("signals=", out["signals"]) 
    print("insight=", (out.get("insight") or "").strip())


if __name__ == "__main__":
    main()

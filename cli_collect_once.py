#!/usr/bin/env python3
"""Collecte ponctuelle: exécute tous les collectors une fois, exporte, puis (optionnel) lance l'analyse.

Usage (PowerShell):
  .\.venv\Scripts\python.exe cli_collect_once.py

Variables d'environnement:
  RUN_ID=...                   # tag run
  ANALYSIS_AUTO_RUN=1          # lancer analyse après export (défaut 1)
  ANALYSIS_ONLY_ON_SIGNALS=1   # ne persister analyse que s'il y a des signaux
  ANALYSIS_EMIT_SIGNALS=1      # exporter signals_latest.json + signals.jsonl
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog
from dotenv import load_dotenv

from main import run_legacy_collection  # réutilise la collecte existante
from pipeline.analysis.events import emit_signals
from pipeline.analysis.persist import save_analysis
from pipeline.analysis.runner import run_automatic_analyses
from pipeline.export_utils import export_latest_and_timestamped

logger = structlog.get_logger(__name__)


def main() -> None:
    load_dotenv()
    run_id = os.getenv("RUN_ID")
    export_dir = os.getenv("EXPORT_DIR", "exports")

    results: list[dict[str, Any]] = asyncio.run(run_legacy_collection())
    latest, ts = export_latest_and_timestamped(results, export_dir, run_id=run_id)
    logger.info("collect_once_exported", latest=latest, timestamped=ts, rows=len(results))

    if os.getenv("ANALYSIS_AUTO_RUN", "1") == "1":
        out = run_automatic_analyses(os.path.join(export_dir, "latest_export.csv"))
        only_on_signals = os.getenv("ANALYSIS_ONLY_ON_SIGNALS", "0") == "1"
        if (not only_on_signals) or out.get("signals"):
            save_analysis(out, export_dir)
            if os.getenv("ANALYSIS_EMIT_SIGNALS", "0") == "1" and out.get("signals"):
                emit_signals(out["signals"], export_dir)
        logger.info("collect_once_analysis_done", **out)


if __name__ == "__main__":
    main()

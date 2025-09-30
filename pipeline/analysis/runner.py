"""Exécution d'analyses automatiques post-collecte.

Contrat minimal:
- Input: DataFrame consolidé (exports/latest_export.csv chargé)
- Output: dict avec 'signals' et 'insights' (texte LLM ou mock)
- Robustesse: best-effort, pas de crash pipeline
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from .dataset import load_latest_export
from .signals import detect_signals
from .llm_exec import run_llm_analysis


def build_prompt_from_signals(signals: list[dict[str, Any]]) -> str:
    if not signals:
        return (
            "Aucune alerte majeure détectée. Résume brièvement l'état du marché crypto "
            "en t'appuyant sur des indicateurs génériques (macro, on-chain, sentiment)."
        )
    lines = ["Synthétise les signaux suivants en un bref insight actionnable:" ]
    for s in signals:
        t = s.get("type", "signal")
        msg = s.get("msg") or str(s)
        lines.append(f"- {t}: {msg}")
    return "\n".join(lines)


def run_automatic_analyses(path: str = "exports/latest_export.csv") -> dict[str, Any]:
    try:
        df = load_latest_export(path)
    except Exception as e:
        return {"status": "no_data", "error": str(e)}

    try:
        signals = detect_signals(df)
    except Exception as e:
        signals = []

    try:
        prompt = build_prompt_from_signals(signals)
        insight = run_llm_analysis(prompt)
    except Exception as e:
        insight = f"[analysis_error] {e}"

    return {
        "status": "ok",
        "signals": signals,
        "insight": insight,
    }

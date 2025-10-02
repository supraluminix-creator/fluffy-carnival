"""Emission des signaux au format JSON/JSONL (append-only).

Par défaut, rien n'est écrit sauf si l'appelant l'active explicitement.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import datetime
from typing import Any


def emit_signals(signals: Iterable[dict[str, Any]], export_dir: str = "exports") -> tuple[str | None, str | None]:
    sigs = list(signals)
    if not sigs:
        return None, None
    os.makedirs(export_dir, exist_ok=True)
    latest = os.path.join(export_dir, "signals_latest.json")
    with open(latest, "w", encoding="utf-8") as f:
        json.dump({"created_at": datetime.utcnow().isoformat() + "Z", "signals": sigs}, f, ensure_ascii=False, indent=2)
    jsonl = os.path.join(export_dir, "signals.jsonl")
    with open(jsonl, "a", encoding="utf-8") as f:
        for s in sigs:
            rec = {"created_at": datetime.utcnow().isoformat() + "Z", **s}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return latest, jsonl

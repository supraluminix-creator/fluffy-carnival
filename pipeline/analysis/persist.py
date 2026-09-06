"""Persistance des résultats d'analyse AI.

Ecrit un fichier latest + un fichier timestampé dans exports/.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any


def save_analysis(result: dict[str, Any], export_dir: str = "exports") -> tuple[str | None, str | None]:
    try:
        os.makedirs(export_dir, exist_ok=True)
        latest = os.path.join(export_dir, "analysis_latest.json")
        with open(latest, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        ts_name = f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        ts_path = os.path.join(export_dir, ts_name)
        with open(ts_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        return latest, ts_path
    except Exception:
        return None, None

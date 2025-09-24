from __future__ import annotations

from typing import List, Optional
from datetime import datetime, timedelta, timezone

from .schemas import Report


_REPORTS: List[Report] = []


def write_report(report: Report) -> None:
    _REPORTS.append(report)


def get_latest_report() -> Optional[Report]:
    if not _REPORTS:
        return None
    return _REPORTS[-1]


def get_report_history(interval: str) -> List[Report]:
    # Simple filtre temporel basé sur meta.run_id (ISO8601 Z)
    now = datetime.now(timezone.utc)
    delta_map = {
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
        "1w": timedelta(weeks=1),
        "1m": timedelta(days=30),
        "1y": timedelta(days=365),
    }
    delta = delta_map.get(interval, timedelta(hours=1))
    cutoff = now - delta

    selected: List[Report] = []
    for r in _REPORTS:
        try:
            ts = datetime.fromisoformat(r.meta.run_id.replace("Z", "+00:00"))
        except Exception:
            continue
        if ts >= cutoff:
            selected.append(r)
    return selected

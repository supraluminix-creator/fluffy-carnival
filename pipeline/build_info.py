from __future__ import annotations

from datetime import datetime, timezone
from typing import TypedDict
import os
import subprocess


# Start time captured at import; used to compute uptime
STARTED_AT_DT = datetime.now(timezone.utc)
STARTED_AT = STARTED_AT_DT.isoformat()


class BuildMetadata(TypedDict, total=False):
    version: str
    git_sha: str
    build_date: str
    started_at: str
    uptime_seconds: float


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "unknown"
    except Exception:
        return os.getenv("GIT_SHA", "unknown")


def build_metadata(include_uptime: bool = True) -> BuildMetadata:
    meta: BuildMetadata = {
        "version": os.getenv("VERSION", "0.1.0"),
        "git_sha": _git_sha(),
        "build_date": os.getenv("BUILD_DATE", ""),
        "started_at": STARTED_AT,
    }
    if include_uptime:
        meta["uptime_seconds"] = (datetime.now(timezone.utc) - STARTED_AT_DT).total_seconds()
    return meta


__all__ = [
    "BuildMetadata",
    "STARTED_AT",
    "STARTED_AT_DT",
    "build_metadata",
]

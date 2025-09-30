from __future__ import annotations

import datetime
import os
import subprocess
from functools import lru_cache
from typing import TypedDict


class BuildMetadata(TypedDict, total=False):
    version: str
    git_sha: str
    build_date: str
    started_at: str
    uptime_seconds: float


# Moment de démarrage du process (UTC)
STARTED_AT_DT = datetime.datetime.utcnow()
STARTED_AT = STARTED_AT_DT.isoformat() + "Z"


@lru_cache(maxsize=1)
def get_git_sha() -> str:
    # Priorité à une variable d'env (CI peut l'injecter)
    env_sha = os.getenv("GIT_SHA") or os.getenv("API_GIT_SHA")
    if env_sha:
        return env_sha[:8]
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def uptime_seconds() -> float:
    try:
        return (datetime.datetime.utcnow() - STARTED_AT_DT).total_seconds()
    except Exception:
        return 0.0


def build_metadata(include_uptime: bool = False) -> BuildMetadata:
    """Retourne un dictionnaire avec les métadonnées de build.

    Paramètres:
      include_uptime: inclure ou non le champ uptime_seconds.
    """
    data: BuildMetadata = {
        "version": os.environ.get("API_VERSION") or os.environ.get("APP_VERSION") or "1.0.0",
        "git_sha": get_git_sha(),
        "build_date": os.environ.get("API_BUILD_DATE") or (datetime.datetime.utcnow().isoformat() + "Z"),
        "started_at": STARTED_AT,
    }
    if include_uptime:
        data["uptime_seconds"] = uptime_seconds()
    return data

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, cast

DEFAULT_MAX_AGE_FEED = int(os.environ.get("SOCIAL_HEALTH_MAX_AGE_FEED_SEC", "3600"))  # 1h
DEFAULT_MAX_AGE_RETWEETERS = int(os.environ.get("SOCIAL_HEALTH_MAX_AGE_RETWEETERS_SEC", "172800"))  # 2j


def _read_stamp(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return cast(dict[str, Any], data)
        return None
    except Exception:
        return None


def check_social_health(
    base_dir: str = "run/social",
    max_age_feed: int = DEFAULT_MAX_AGE_FEED,
    max_age_retweeters: int = DEFAULT_MAX_AGE_RETWEETERS,
    allow_missing_feed: bool = False,
) -> int:
    now = int(time.time())
    root = Path(base_dir)

    feed = _read_stamp(root / "last_success_feed.json")
    retw = _read_stamp(root / "last_success_retweeters.json")

    problems: list[str] = []

    if feed:
        age = now - int(feed.get("ts", 0))
        if age > max_age_feed:
            problems.append(f"feed too old: {age}s > {max_age_feed}s")
    else:
        if not allow_missing_feed:
            problems.append("feed missing")

    if retw:
        age = now - int(retw.get("ts", 0))
        if age > max_age_retweeters:
            problems.append(f"retweeters too old: {age}s > {max_age_retweeters}s")
    else:
        # retweeters peut etre inactif (opt-in): on n'alerte pas si stamp absent
        pass

    if problems:
        print("; ".join(problems))
        return 1

    print("social health OK")
    return 0


if __name__ == "__main__":
    # Defaults from environment
    env_base_dir = os.environ.get("SOCIAL_HEALTH_DIR", "run/social")
    env_max_age_feed = int(os.environ.get("SOCIAL_HEALTH_MAX_AGE_FEED_SEC", str(DEFAULT_MAX_AGE_FEED)))
    env_max_age_retw = int(os.environ.get("SOCIAL_HEALTH_MAX_AGE_RETWEETERS_SEC", str(DEFAULT_MAX_AGE_RETWEETERS)))
    env_allow_missing = os.environ.get("SOCIAL_HEALTH_ALLOW_MISSING_FEED", "0").lower() in {"1", "true", "yes", "on"}

    parser = argparse.ArgumentParser(description="Social health-check: validates freshness of last_success_* stamps.")
    parser.add_argument(
        "--dir",
        dest="base_dir",
        default=env_base_dir,
        help=f"Base directory for stamps (default: {env_base_dir})",
    )
    parser.add_argument(
        "--max-age-feed",
        dest="max_age_feed",
        type=int,
        default=env_max_age_feed,
        help=f"Max age for feed in seconds (default: {env_max_age_feed})",
    )
    parser.add_argument(
        "--max-age-retweeters",
        dest="max_age_retweeters",
        type=int,
        default=env_max_age_retw,
        help=f"Max age for retweeters in seconds (default: {env_max_age_retw})",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--allow-missing-feed",
        dest="allow_missing_feed",
        action="store_true",
        default=env_allow_missing,
        help="Allow missing feed stamp without error",
    )
    group.add_argument(
        "--no-allow-missing-feed",
        dest="allow_missing_feed",
        action="store_false",
        help="Do not allow missing feed stamp (default unless env set)",
    )

    args = parser.parse_args()

    code = check_social_health(
        base_dir=args.base_dir,
        max_age_feed=args.max_age_feed,
        max_age_retweeters=args.max_age_retweeters,
        allow_missing_feed=args.allow_missing_feed,
    )
    sys.exit(code)

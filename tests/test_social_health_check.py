from __future__ import annotations

import json
from pathlib import Path

from scripts.social_health_check import check_social_health


def test_social_health_missing_feed(tmp_path: Path, monkeypatch) -> None:
    d = tmp_path / "run" / "social"
    d.mkdir(parents=True, exist_ok=True)
    # pas de last_success_feed.json
    # retweeters absent autorise
    code = check_social_health(base_dir=str(d))
    assert code == 1


def test_social_health_ok(tmp_path: Path, monkeypatch) -> None:
    d = tmp_path / "run" / "social"
    d.mkdir(parents=True, exist_ok=True)
    (d / "last_success_feed.json").write_text(json.dumps({"ts": 9999999999}), encoding="utf-8")
    code = check_social_health(base_dir=str(d), max_age_feed=10**12)
    assert code == 0


def test_social_health_allow_missing_feed(tmp_path: Path) -> None:
    d = tmp_path / "run" / "social"
    d.mkdir(parents=True, exist_ok=True)
    # pas de last_success_feed.json, mais on tolère l'absence
    code = check_social_health(base_dir=str(d), allow_missing_feed=True)
    assert code == 0

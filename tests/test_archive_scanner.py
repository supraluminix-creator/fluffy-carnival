from __future__ import annotations

from pathlib import Path

from tools.archive_repo import scan_repo


def test_archive_scanner_basic(tmp_path: Path, monkeypatch):
    # Create a mini repo structure
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "notebooks").mkdir()
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "dashboard.py").write_text("print('dash')", encoding="utf-8")
    (tmp_path / "streamlit_app.py").write_text("import streamlit as st", encoding="utf-8")
    (tmp_path / "README.md").write_text("ok", encoding="utf-8")

    # Patch repo root resolver to our tmp
    from tools import archive_repo as ar

    def _fake_root() -> Path:
        return tmp_path

    monkeypatch.setattr(ar, "get_repo_root", _fake_root)

    items = scan_repo(tmp_path)
    archived_paths = {i.path.name for i in items}
    # We expect the 'notebooks' dir, 'ui' dir, and the streamlit script to be candidates
    assert "notebooks" in archived_paths
    assert "ui" in archived_paths
    assert "streamlit_app.py" in archived_paths

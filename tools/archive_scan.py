"""Repo scanner to propose ARCHIVE/KEEP/REVIEW decisions.

Usage (Windows PowerShell):
    .\\.venv\\Scripts\\python.exe tools\\archive_scan.py --write

It writes two artifacts at repo root:
  - ARCHIVE_SCAN.json: structured list of files with decision & reason
  - ARCHIVE_SCAN.md: human-readable summary

Rules:
  - ARCHIVE if path matches UI/demo/front/notebook/powerShell/dashboard patterns
  - KEEP for core paths (pipeline/, scheduler/, integrations/, schema/, typings/)
  - REVIEW otherwise
"""
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


ARCHIVE_DIR_KEYWORDS = {
    "ui", "dashboard", "dashboards", "frontend", "front", "streamlit",
    "notebook", "notebooks", "demos", "demo",
}

ARCHIVE_FILE_EXTENSIONS = {
    ".ipynb", ".ps1", ".pbix", ".pptx", ".ppt", ".bat", ".cmd",
}

ARCHIVE_FILE_KEYWORDS = {
    "streamlit", "dashboard", "notebook", "demo", "example", "powershell",
}

KEEP_TOP_LEVEL_DIRS = {
    "pipeline", "scheduler", "integrations", "schema", "typings", "tests", "api",
}

EXCLUDE_DIRS = {".git", ".venv", "__pycache__", "archive-"}

DO_NOT_ARCHIVE_FILES = {
    ".env.example",
    "secrets.example.env",
}


@dataclass
class ScanEntry:
    path: str
    decision: str  # KEEP|ARCHIVE|REVIEW
    reason: str


def _should_exclude_dir(path: Path) -> bool:
    name = path.name.lower()
    if name in EXCLUDE_DIRS:
        return True
    # Any dir starting with archive-
    return name.startswith("archive-")


def iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dpath = Path(dirpath)
        # Prune excluded dirs
        dirnames[:] = [d for d in dirnames if not _should_exclude_dir(dpath / d)]
        for fn in filenames:
            yield dpath / fn


def decide(path: Path) -> ScanEntry:
    rel = path.relative_to(REPO_ROOT).as_posix()
    parts = [p.lower() for p in rel.split('/')]
    top = parts[0] if parts else ""
    base = Path(rel).name

    # Default reasons
    decision = "REVIEW"
    reason = "no rule matched"

    # Explicit keep for placeholder/example secret files
    if base in DO_NOT_ARCHIVE_FILES:
        return ScanEntry(rel, "KEEP", f"explicit keep for {base}")

    # Keep core paths
    if top in KEEP_TOP_LEVEL_DIRS:
        return ScanEntry(rel, "KEEP", f"top-level core dir: {top}")

    # Keep current prod examples (small, maintained)
    if top == "examples":
        return ScanEntry(rel, "KEEP", "examples kept (core demo)")

    # Archive by directory keywords
    if any(k in parts for k in ARCHIVE_DIR_KEYWORDS):
        return ScanEntry(rel, "ARCHIVE", "dir keyword match")

    # Archive by filename keywords/ext
    low = rel.lower()
    if any(k in low for k in ARCHIVE_FILE_KEYWORDS):
        return ScanEntry(rel, "ARCHIVE", "file keyword match")
    if Path(rel).suffix.lower() in ARCHIVE_FILE_EXTENSIONS:
        return ScanEntry(rel, "ARCHIVE", f"extension {Path(rel).suffix}")

    # Non-core top-level dirs (docs, scripts, tools) -> REVIEW, except explicit archives
    if top in {"docs", "scripts", "tools", "archived", "improvements"}:
        decision = "REVIEW"
        reason = f"non-core top-level dir: {top}"
        return ScanEntry(rel, decision, reason)

    # Specific known files to archive
    if rel in {"streamlit_app.py"}:
        return ScanEntry(rel, "ARCHIVE", "explicit streamlit")

    return ScanEntry(rel, decision, reason)


def write_outputs(entries: list[ScanEntry]) -> None:
    json_path = REPO_ROOT / "ARCHIVE_SCAN.json"
    md_path = REPO_ROOT / "ARCHIVE_SCAN.md"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([asdict(e) for e in entries], f, ensure_ascii=False, indent=2)
    # Markdown summary
    arch = [e for e in entries if e.decision == "ARCHIVE"]
    keep = [e for e in entries if e.decision == "KEEP"]
    rev = [e for e in entries if e.decision == "REVIEW"]
    lines = ["# Archive scan", "", f"Root: {REPO_ROOT}", ""]
    lines += [f"- KEEP: {len(keep)}", f"- ARCHIVE: {len(arch)}", f"- REVIEW: {len(rev)}", ""]
    lines += ["## ARCHIVE", ""] + [f"- {e.path} — {e.reason}" for e in arch] + [""]
    lines += ["## REVIEW", ""] + [f"- {e.path} — {e.reason}" for e in rev[:200]] + [""]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write ARCHIVE_SCAN.json & .md at repo root")
    args = ap.parse_args()
    entries = [decide(p) for p in iter_files(REPO_ROOT)]
    # Keep only files within the repo (skip .git etc already pruned)
    if args.write:
        write_outputs(entries)
        print("Scan written to ARCHIVE_SCAN.json and ARCHIVE_SCAN.md")
    else:
        print(json.dumps([asdict(e) for e in entries[:30]], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

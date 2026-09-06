"""Execute archiving based on scan rules.

This script:
    - Runs archive_scan to produce a list of candidates
    - Creates archive-YYYYMMDD_HHMMSS directory at repo root
    - Moves files classified ARCHIVE into it (preserving structure)
    - Zips the archive directory (skipped on --dry-run or when no items moved)
    - Writes ARCHIVE_REPORT.md inside the archive directory with details (date, git HEAD, counts, notes)

Usage (PowerShell):
    .\\.venv\\Scripts\\python.exe tools\\archive_exec.py --dry-run  # preview only
    .\\.venv\\Scripts\\python.exe tools\\archive_exec.py             # execute moves
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_JSON = REPO_ROOT / "ARCHIVE_SCAN.json"


def _git_head() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
        return out
    except Exception:
        return "unknown"


def load_scan() -> list[dict]:
    if not SCAN_JSON.exists():
        raise SystemExit("ARCHIVE_SCAN.json missing. Run tools/archive_scan.py --write first.")
    data = json.loads(SCAN_JSON.read_text(encoding="utf-8"))
    if not isinstance(data, list):  # pragma: no cover (defensive)
        raise SystemExit("Invalid ARCHIVE_SCAN.json")
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="do not move files, only print plan")
    args = ap.parse_args()

    scan = load_scan()
    archive_items = [e for e in scan if e.get("decision") == "ARCHIVE"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    arc_dir = REPO_ROOT / f"archive-{ts}"
    arc_dir.mkdir(parents=True, exist_ok=True)

    moved: list[str] = []
    for item in archive_items:
        rel = item["path"]
        src = REPO_ROOT / rel
        if not src.exists():
            continue
        dst = arc_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if args.dry_run:
            print(f"DRY-RUN would move: {rel} -> {dst}")
        else:
            shutil.move(str(src), str(dst))
            moved.append(rel)

    # If dry-run, write a plan and skip zipping
    if args.dry_run:
        plan = arc_dir / f"DRY_RUN_PLAN_{ts}.md"
        lines = [
            "# Dry-run plan",
            "",
            f"Date: {datetime.now().isoformat(timespec='seconds')}",
            f"Git HEAD: {_git_head()}",
            "",
            f"Planned moves: {len(archive_items)}",
            "",
        ]
        for item in archive_items:
            rel = item["path"]
            lines.append(f"- {rel} -> {arc_dir / rel}")
        plan.write_text("\n".join(lines), encoding="utf-8")
        print(f"Dry-run complete. Plan: {plan}")
        # No zip in dry-run to avoid clutter
        # Still write a lightweight report for traceability
        report = arc_dir / "ARCHIVE_REPORT.md"
        report.write_text(
            "\n".join(
                [
                    "# Archive report (dry-run)",
                    "",
                    f"Date: {datetime.now().isoformat(timespec='seconds')}",
                    f"Git HEAD: {_git_head()}",
                    f"Archive directory: {arc_dir.name}",
                    "",
                    "Moved items: 0 (dry-run)",
                ]
            ),
            encoding="utf-8",
        )
        print(f"Report written: {report}")
        return

    # If no items were moved (either no candidates or missing files), skip zipping
    if not moved:
        report = arc_dir / "ARCHIVE_REPORT.md"
        report.write_text(
            "\n".join(
                [
                    "# Archive report",
                    "",
                    f"Date: {datetime.now().isoformat(timespec='seconds')}",
                    f"Git HEAD: {_git_head()}",
                    f"Archive directory: {arc_dir.name}",
                    "",
                    "Moved items: 0",
                    "",
                    "## Notes",
                    "- No items to move; zip skipped.",
                ]
            ),
            encoding="utf-8",
        )
        print(f"Archive run completed: no items to move. Report: {report}")
        return

    # Zip archive directory
    zip_path = REPO_ROOT / f"{arc_dir.name}.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=arc_dir)

    # Report
    report = arc_dir / "ARCHIVE_REPORT.md"
    head = _git_head()
    lines = [
        "# Archive report",
        "",
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        f"Git HEAD: {head}",
        f"Archive directory: {arc_dir.name}",
        f"Archive zip: {zip_path.name}",
        "",
        f"Moved items: {len(moved)}",
        "",
        "## Items",
    ]
    lines += [f"- {p}" for p in moved]
    lines += [
        "",
        "## Notes",
        "- Quickwins: scan+archive scripted; core left intact.",
        "- Next steps: migrate remaining collectors to unified HTTP; update CI and secrets policies.",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {report}")


if __name__ == "__main__":
    main()

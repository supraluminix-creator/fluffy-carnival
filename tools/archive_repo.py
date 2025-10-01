"""Repo archiver: scan, move non-core (UI/demo/notebooks/PowerShell) to timestamped archive, zip, and report.

Usage (Windows PowerShell examples):
  # Scan only (no changes), write scan report at archive/scan-<ts>.md
  python tools/archive_repo.py --scan-only

  # Archive (move + zip + report)
  python tools/archive_repo.py --run

Rules (default):
  ARCHIVE if any is true:
   - filename ext in { .ipynb, .pbix, .ppt, .pptx, .ps1 }
   - path contains ui|streamlit|dashboard|frontend (case-insensitive)
   - filename contains 'streamlit' (e.g., streamlit_app.py)
   - folder name equals one of { 'notebooks', 'demo', 'demos' }

  KEEP folders by default: pipeline, api, scheduler, integrations, typings, schema, data, run, exports, tests, tools (except targeted files), docs.
  Skip already archived folders: archived/, archive-*/

Notes:
 - Nothing is deleted. We move files/dirs to archive-YYYYMMDD_HHMMSS/ at repo root, then zip.
 - A detailed report is generated with git HEAD, counts, reasons, and errors.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import time
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# --------------------------- Config & Rules ---------------------------

ARCHIVE_EXTS = {".ipynb", ".pbix", ".ppt", ".pptx", ".ps1"}
# Segment-based keywords (match full path segment only)
ARCHIVE_SEGMENT_KEYWORDS = {"ui", "streamlit", "dashboard", "frontend"}
# Filename substring keywords (more permissive, but limited to filenames)
ARCHIVE_FILENAME_SUBSTR = {"streamlit"}
ARCHIVE_FOLDERS = {"notebooks", "demo", "demos"}

KEEP_TOP_DIRS = {
    "pipeline",
    "api",
    "scheduler",
    "integrations",
    "typings",
    "schema",
    "data",
    "run",
    "exports",
    "tests",
    "tools",
    "docs",
}

# Filenames that must never be archived (placeholders / examples kept in repo)
DO_NOT_ARCHIVE_FILENAMES = {".env.example", "secrets.example.env"}


@dataclass
class ScanItem:
    path: Path
    reason: str


def is_within(path: Path, ancestor: Path) -> bool:
    try:
        path.relative_to(ancestor)
        return True
    except ValueError:
        return False


def get_repo_root() -> Path:
    here = Path(__file__).resolve()
    # repo root is project root (two parents up from tools/)
    root = here.parent.parent
    return root


def git_head(root: Path) -> str:
    try:
        rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        return rev
    except Exception:
        return "unknown"


def should_skip(path: Path, root: Path) -> bool:
    # Skip the archive target folders themselves, venvs, git, and already archived content
    parts = {p.name.lower() for p in path.parents}
    name = path.name.lower()
    if name.startswith("archive-"):
        return True
    if any(n.startswith("archive-") for n in parts):
        return True
    if ".git" in parts or name == ".git":
        return True
    if ".venv" in parts or name == ".venv":
        return True
    # Skip existing archived folder at repo root
    return name == "archived" and path.is_dir() and path.parent == root


def classify_path(p: Path, root: Path) -> tuple[str, str] | tuple[None, None]:
    """Return (action, reason) where action in {ARCHIVE, KEEP, REVIEW}. None if not applicable.

    We only return ARCHIVE/REVIEW for candidates; KEEP is implicit and not listed by default.
    """
    if should_skip(p, root):
        return (None, None)

    rel = p.relative_to(root)
    parts = [part.lower() for part in rel.parts]
    name = p.name.lower()
    # Explicit keep for placeholder/example secret files
    if name in DO_NOT_ARCHIVE_FILENAMES:
        return (None, None)
    # Helper: does any path segment match a keyword exactly?
    def has_segment_keyword() -> bool:
        return any(seg in ARCHIVE_SEGMENT_KEYWORDS for seg in parts)

    # Ignore top-level keep dirs wholesale unless they match specific archive rules
    if rel.parts and rel.parts[0] in KEEP_TOP_DIRS:
        # Within tools/, still archive PowerShell scripts
        if rel.parts[0] == "tools" and p.suffix.lower() == ".ps1":
            return ("ARCHIVE", "PowerShell script (tools)")
        # Within any keep dir, only archive explicit UI or file types
        if has_segment_keyword():
            return ("ARCHIVE", "UI/Dashboard segment within keep dir")
        if p.is_file() and p.suffix.lower() in ARCHIVE_EXTS:
            return ("ARCHIVE", f"File extension {p.suffix.lower()}")
        if any(sub in name for sub in ARCHIVE_FILENAME_SUBSTR):
            return ("ARCHIVE", "Streamlit file")
        return (None, None)

    # Top-level files
    if p.is_file():
        if p.suffix.lower() in ARCHIVE_EXTS:
            return ("ARCHIVE", f"File extension {p.suffix.lower()}")
        if "streamlit" in name:
            return ("ARCHIVE", "Streamlit file")

    # Directory-based rules
    if p.is_dir():
        base = name
        if base in ARCHIVE_FOLDERS:
            return ("ARCHIVE", f"Folder name {base}")
        if base in ARCHIVE_SEGMENT_KEYWORDS:
            return ("ARCHIVE", f"Folder keyword {base}")

    # Path contains UI keywords (case-insensitive)
    if has_segment_keyword():
        return ("ARCHIVE", "UI/Dashboard segment in path")

    # Default: not a candidate
    return (None, None)


def scan_repo(root: Path) -> list[ScanItem]:
    items: list[ScanItem] = []
    for p in root.rglob("*"):
        # Skip directories we don't want to traverse deeply (like .git, .venv, archive-* zips)
        if p.is_dir() and should_skip(p, root):
            # Don't traverse inside skipped dirs
            continue
        action, reason = classify_path(p, root)
        if action == "ARCHIVE":
            items.append(ScanItem(p, reason or "archived_by_rule"))
    # De-duplicate by top-level directory where moving a directory will capture children
    # Prefer directories first; remove children of directories from the list
    dirs = {it.path for it in items if it.path.is_dir()}
    filtered: list[ScanItem] = []
    for it in items:
        if any(is_within(it.path, d) and it.path != d for d in dirs):
            continue
        filtered.append(it)
    return filtered


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write_report(report_path: Path, head: str, moved: list[tuple[Path, Path, str]], errors: list[str]) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    lines.append("# Archive Report\n\n")
    lines.append(f"Date: {ts}\n\n")
    lines.append(f"Git HEAD: {head}\n\n")
    lines.append(f"Moved items: {len(moved)}\n\n")
    if moved:
        lines.append("## Items\n\n")
        for src, dst, reason in moved:
            lines.append(f"- {src.as_posix()} -> {dst.as_posix()}  —  {reason}\n")
    if errors:
        lines.append("\n## Errors\n\n")
        lines.extend(f"- {e}\n" for e in errors)
    lines.append("\n## Quickwins\n\n- Script executed with default rules.\n- No deletions, all moves reversible via archive folder or zip.\n")
    lines.append("\n## Next steps\n\n- Review archived list and restore any false positives.\n- Open PR with this report attached.\n")
    report_path.write_text("".join(lines), encoding="utf-8")


def make_zip(source_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in source_dir.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(source_dir).as_posix())


def perform_archive(
    root: Path,
    scan_items: list[ScanItem],
    archive_root: Path,
    dry_run: bool = False,
) -> tuple[list[tuple[Path, Path, str]], list[str]]:
    moved: list[tuple[Path, Path, str]] = []
    errors: list[str] = []
    moved_root = archive_root / "moved"
    ensure_dir(moved_root)
    for it in scan_items:
        rel = it.path.relative_to(root)
        dst = moved_root / rel
        ensure_dir(dst.parent)
        try:
            # If destination exists, rename with suffix
            target = dst
            if target.exists():
                target = dst.with_name(dst.name + f".__arch__{int(time.time())}")
            if dry_run:
                moved.append((it.path, target, it.reason))
                continue
            shutil.move(str(it.path), str(target))
            moved.append((it.path, target, it.reason))
        except Exception as e:
            errors.append(f"move_failed: {it.path} -> {dst} : {e}")
    return moved, errors


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scan and archive non-core assets (UI/demos/notebooks/PowerShell)")
    ap.add_argument("--run", action="store_true", help="Execute archive (move + zip + report)")
    ap.add_argument("--scan-only", action="store_true", help="Only scan and write scan report (no changes)")
    ap.add_argument("--out", default=None, help="Optional archive folder name (default: archive-<timestamp>)")
    ap.add_argument("--dry-run", action="store_true", help="Do not move files; write a dry-run plan only")
    args = ap.parse_args(list(argv) if argv is not None else None)

    root = get_repo_root()
    head = git_head(root)
    ts = time.strftime("%Y%m%d_%H%M%S")
    archive_name = args.out or f"archive-{ts}"
    archive_root = root / archive_name
    ensure_dir(archive_root)

    items = scan_repo(root)
    # Write scan report regardless
    scan_report = archive_root / f"scan_{ts}.md"
    with open(scan_report, "w", encoding="utf-8") as f:
        f.write(f"# Scan Report\n\nDate: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\nGit HEAD: {head}\n\n")
        f.write(f"Candidates to archive: {len(items)}\n\n")
        for it in items:
            f.write(f"- {it.path.relative_to(root).as_posix()} — {it.reason}\n")

    if args.scan_only and not args.run:
        print(f"Scan-only report written to {scan_report}")
        return 0

    moved, errors = perform_archive(root, items, archive_root, dry_run=args.dry_run)
    # Write archive report
    report_path = archive_root / f"ARCHIVE_REPORT_{ts}.md"
    write_report(report_path, head, moved, errors)

    # If dry-run, also write a simple plan file and skip zipping
    if args.dry_run:
        plan = archive_root / f"DRY_RUN_PLAN_{ts}.md"
        with open(plan, "w", encoding="utf-8") as pf:
            pf.write(f"# Dry-run plan\n\nPlanned moves: {len(moved)}\n\n")
            for src, dst, reason in moved:
                pf.write(f"- {src.as_posix()} -> {dst.as_posix()}  —  {reason}\n")
        print(f"Dry-run complete. Plan: {plan}")
        return 0

    # If no items were moved, skip creating a zip to avoid clutter
    if not moved:
        print(f"Archive run completed: no items to move. Report: {report_path}")
        return 0

    # Zip
    zip_path = root / f"{archive_name}.zip"
    make_zip(archive_root, zip_path)
    print(f"Archive completed: {archive_root} -> {zip_path}")
    print(f"Report: {report_path}")
    if errors:
        print(f"Errors: {len(errors)} (see report)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

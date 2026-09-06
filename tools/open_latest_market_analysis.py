from __future__ import annotations

import argparse
import webbrowser
from contextlib import suppress
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = REPO_ROOT / "exports" / "analysis"


def _find_latest_analysis() -> Path | None:
    if not ANALYSIS_DIR.exists():
        return None
    files = [p for p in ANALYSIS_DIR.glob("market_analysis_*.md") if p.is_file()]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Open latest market analysis Markdown report")
    ap.add_argument("--dry-run", action="store_true", help="Do not open, just print the path")
    args = ap.parse_args()

    p = _find_latest_analysis()
    if not p:
        print("No analysis report found. Run tools/market_analysis_prompt.py first.")
        return 1
    if not args.dry_run:
        with suppress(Exception):
            webbrowser.open_new_tab(p.as_uri())
    print(f"Opened: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

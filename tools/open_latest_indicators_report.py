from __future__ import annotations

import argparse
import json
import os
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORTS_DIR = REPO_ROOT / "exports"


def _read_latest_report_path() -> Path | None:
    # Prefer an explicit env var
    env_path = os.getenv("INDICATORS_AUDIT_HTML_PATH")
    if env_path:
        p = Path(env_path)
        return p if p.exists() else None
    # Default path
    default = EXPORTS_DIR / "indicators" / "report.html"
    if default.exists():
        return default
    # Try to look into the indicators manifest for the last path (to guide user)
    mani = EXPORTS_DIR / "indicators" / "indicators_manifest.jsonl"
    if mani.exists():
        try:
            last: dict | None = None
            with mani.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    last = json.loads(line)
            if last:
                # Just return default if exists, else None
                return default if default.exists() else None
        except Exception:
            pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Open latest indicators audit report (HTML or JSON)")
    parser.add_argument("--json", action="store_true", help="Open the JSON report instead of HTML")
    parser.add_argument("--dry-run", action="store_true", help="Do not open browser, just print path")
    args = parser.parse_args()

    if args.json:
        # Prefer explicit env JSON path, else the default sidecar
        env_json = os.getenv("INDICATORS_AUDIT_JSON_PATH")
        jpath = Path(env_json) if env_json else EXPORTS_DIR / "indicators" / "report.json"
        if not jpath.exists():
            print("No JSON report found. Enable JSON output or run the audit with JSON export enabled.")
            return 1
        if not args.dry_run:
            from contextlib import suppress
            with suppress(Exception):
                webbrowser.open_new_tab(jpath.as_uri())
        print(f"Opened: {jpath}")
        return 0

    path = _read_latest_report_path()
    if not path:
        print("No HTML report found. Run the audit with --html first.")
        return 1
    if not args.dry_run:
        from contextlib import suppress
        with suppress(Exception):
            webbrowser.open_new_tab(path.as_uri())
    print(f"Opened: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

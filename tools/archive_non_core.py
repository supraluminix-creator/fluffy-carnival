from __future__ import annotations

import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ARCHIVE_MAP = [
    # (path relative to root, reason)
    ("streamlit_app.py", "UI non essentielle"),
    ("scripts/run_market_analysis.ps1", "Automatisation non nécessaire"),
    ("docs/", "Docs volumineuses, conserver un minimum"),
]


def timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def main() -> int:
    archived_dir = ROOT / "archived"
    ensure_dir(archived_dir)

    notes = []
    for rel, reason in ARCHIVE_MAP:
        src = ROOT / rel
        if not src.exists():
            continue
        dst = archived_dir / rel
        ensure_dir(dst.parent)
        if src.is_dir():
            shutil.move(str(src), str(dst))
        else:
            ensure_dir(dst.parent)
            shutil.move(str(src), str(dst))
        notes.append(f"- {rel} → archived ({reason})")

    if notes:
        note_path = archived_dir / f"ARCHIVE_NOTES_{timestamp()}.md"
        with open(note_path, "w", encoding="utf-8") as f:
            f.write("# Archive Notes\n\n")
            f.write("\n".join(notes) + "\n")
        print(f"Archive notes written: {note_path}")
    else:
        print("Nothing archived (no matching paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

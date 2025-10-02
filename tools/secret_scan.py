#!/usr/bin/env python3
"""Scan heuristique simple des secrets dans le repo.

Usage:
    python tools/secret_scan.py [--fail-on-find]

Logique:
- Cherche patterns regex connus (API keys, hex longs, préfixes courants)
- Ignore chemins listés (venv, .git, dist, build, parquet, *.db)

Limitations:
- Faux positifs possibles.
- Ne remplace pas un outil spécialisé (trufflehog, detect-secrets).
"""
from __future__ import annotations

import argparse
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("hex_64", re.compile(r"\b[0-9a-fA-F]{64}\b")),
    ("hex_48", re.compile(r"\b[0-9a-fA-F]{48}\b")),
    (
        "uuid_v4",
        re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"),
    ),
    ("binance_like", re.compile(r"\b[0-9A-Za-z]{32,64}\b")),
    ("coingecko_prefix", re.compile(r"CG-[0-9A-Za-z]{20,}")),
    ("token_metrics", re.compile(r"tm-[0-9a-fA-F-]{30,}")),
    # Exige au moins 24 caractères pour réduire les faux positifs et évite de matcher des appels de code
    ("generic_api_key", re.compile(r"\b[A-Z0-9_]*API_KEY\s*[=:\s]\s*[0-9A-Za-z-_]{24,}\b")),
]

IGNORE_DIRS = {
    ".git",
    ".venv",
    "dist",
    "build",
    "__pycache__",
    "data",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "logs",
    "run",
    "exports",
}
IGNORE_EXT = {".pyc", ".parquet", ".db", ".sqlite"}
MAX_FILE_SIZE = 200_000  # 200 KB heuristique

@dataclass
class Finding:
    path: Path
    line_no: int
    pattern: str
    excerpt: str


def iter_text_files(root: Path) -> Iterator[Path]:
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        # Ignore environnements locaux versionnés par erreur
        if p.name in {".env", ".env.local"}:
            continue
        if p.suffix in IGNORE_EXT:
            continue
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        # Ignore archive outputs (archive-YYYYMMDD_*) and streamlit secrets samples
        if any(part.startswith("archive-") for part in p.parts):
            continue
        if any(part == ".streamlit" for part in p.parts):
            continue
        try:
            if p.stat().st_size > MAX_FILE_SIZE:
                continue
        except OSError:
            continue
        yield p


def scan_file(path: Path) -> Iterable[Finding]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    findings: list[Finding] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        # Skip placeholder markers
        if "REPLACE_ME" in line:
            continue
        lowered = line.lower()
        if "password" in lowered or "secret" in lowered:
            # Accept scanning anyway
            pass
        for name, pat in PATTERNS:
            for m in pat.finditer(line):
                val = m.group(0)
                # heuristique simple: ignorer ce qui ressemble à un hash de commit git
                if re.fullmatch(r"[0-9a-f]{40}", val):
                    continue
                findings.append(Finding(path=path, line_no=idx, pattern=name, excerpt=line.strip()[:160]))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fail-on-find", action="store_true", help="Retour code 1 si au moins une empreinte détectée")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    all_findings: list[Finding] = []
    for f in iter_text_files(root):
        all_findings.extend(scan_file(f))

    if not all_findings:
        print("[secret-scan] OK: aucune empreinte suspecte")
        return 0

    print(f"[secret-scan] WARN: {len(all_findings)} occurrences potentielles:")
    for fd in all_findings[:100]:
        print(f" - {fd.path.relative_to(root)}:{fd.line_no} [{fd.pattern}] {fd.excerpt}")
    if len(all_findings) > 100:
        print("   ... (troncation)")

    return 1 if args.fail_on_find else 0

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

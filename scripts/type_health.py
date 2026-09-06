#!/usr/bin/env python
"""Type health report.

Scans project packages to classify modules into:
- strict: covered by a mypy override with disallow_untyped_defs
- strict+imports: also has ignore_missing_imports=false
- incomplete_strict: strict plus disallow_incomplete_defs
- legacy: everything else under pipeline/collectors or core packages

Outputs a concise table & guidance for next tightening steps.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
TARGET_PACKAGES = ["pipeline/collectors", "api", "scheduler"]


@dataclass(frozen=True)
class ModuleStatus:
    module: str
    strict: bool
    strict_imports: bool
    incomplete_defs: bool

    @property
    def category(self) -> str:
        if self.strict and self.incomplete_defs and self.strict_imports:
            return "strict+imports+incomplete"
        if self.strict and self.incomplete_defs:
            return "strict+incomplete"
        if self.strict and self.strict_imports:
            return "strict+imports"
        if self.strict:
            return "strict"
        return "legacy"


def load_overrides() -> list[dict]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    tool = data.get("tool", {})
    mypy = tool.get("mypy", {})
    overrides: list[dict] = mypy.get("overrides", [])
    return overrides


def expand_module_patterns(patterns: Iterable[str]) -> set[str]:
    expanded: set[str] = set()
    for pat in patterns:
        # Strip trailing .* for package patterns; treat single module names as-is
        if pat.endswith(".*"):
            expanded.add(pat[:-2])
        else:
            expanded.add(pat)
    return expanded


def discover_python_modules() -> list[str]:
    modules: list[str] = []
    for pkg in TARGET_PACKAGES:
        base = PROJECT_ROOT / pkg
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            modules.append(rel[:-3].replace("/", "."))  # strip .py
    return sorted(modules)


def classify_modules() -> list[ModuleStatus]:
    overrides = load_overrides()
    strict_patterns: set[str] = set()
    strict_imports_patterns: set[str] = set()
    incomplete_patterns: set[str] = set()
    for ov in overrides:
        mods = expand_module_patterns(ov.get("module", []))
        if ov.get("disallow_untyped_defs"):
            strict_patterns.update(mods)
        if ov.get("ignore_missing_imports") is False:
            strict_imports_patterns.update(mods)
        if ov.get("disallow_incomplete_defs"):
            incomplete_patterns.update(mods)
    statuses: list[ModuleStatus] = []
    for mod in discover_python_modules():
        base = mod  # collectors are individual modules already
        status = ModuleStatus(
            module=mod,
            strict=any(base.startswith(p) for p in strict_patterns),
            strict_imports=any(base.startswith(p) for p in strict_imports_patterns),
            incomplete_defs=any(base.startswith(p) for p in incomplete_patterns),
        )
        statuses.append(status)
    return statuses


def summarize(statuses: list[ModuleStatus]) -> None:
    from collections import Counter

    counts = Counter(s.category for s in statuses)
    total = len(statuses)
    print("Type Health Summary")
    print("===================")
    for cat, cnt in sorted(counts.items()):
        pct = (cnt / total) * 100 if total else 0
        print(f"{cat:28s} {cnt:3d} ({pct:5.1f}%)")
    print()
    print("Next Recommended Steps")
    if counts.get("legacy", 0):
        print("- Promote 1–2 legacy collectors with highest runtime importance to strict+imports.")
    if counts.get("strict", 0):
        print("- Add ignore_missing_imports = false to remaining strict-only modules.")
    if counts.get("strict+imports", 0):
        print("- Trial disallow_incomplete_defs on a second/third module if noise stays low.")
    if counts.get("strict+imports+incomplete", 0) and not counts.get("legacy", 0):
        print("- Consider flipping global ignore_missing_imports to false (pilot complete).")
    print()
    print("Detailed Modules")
    for s in statuses:
        print(f"{s.module:50s} -> {s.category}")


def main() -> None:
    statuses = classify_modules()
    summarize(statuses)


if __name__ == "__main__":  # pragma: no cover
    main()

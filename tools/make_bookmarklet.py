#!/usr/bin/env python3
"""
Helper to generate a minified bookmarklet URL for bookmarklets/inject_prompt.js
Usage:
    python tools/make_bookmarklet.py
Outputs a file tools/inject_prompt.bookmarklet.txt containing the URL.
"""

from __future__ import annotations

import pathlib
import re
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "bookmarklets" / "inject_prompt.js"
OUT = ROOT / "tools" / "inject_prompt.bookmarklet.txt"

JS_PREFIX = "javascript:"


def _minify(js: str) -> str:
    # Remove /* */ comments
    js = re.sub(r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/", "", js)
    # Remove // comments (not inside strings)
    js = re.sub(r"(^|\n)\s*//.*", "\\1", js)
    # Collapse whitespace
    js = re.sub(r"\s+", " ", js)
    # Trim
    return js.strip()


def main() -> None:
    src = SRC.read_text(encoding="utf-8")
    code = _minify(src)
    # Ensure it starts with an IIFE; if already has (function(){}) wrap is fine
    if not code.startswith("("):
        code = f"(function(){{ {code} }})();"
    payload = JS_PREFIX + urllib.parse.quote(code, safe="!()*',;:@-._~")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(payload, encoding="utf-8")
    print(f"Bookmarklet URL written to {OUT}")


if __name__ == "__main__":
    main()

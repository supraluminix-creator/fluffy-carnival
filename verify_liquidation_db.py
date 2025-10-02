"""Compatibility shim for historical path.

This module delegates to tools.verify_pipeline CLI to inspect liquidations DB and
basic health checks. It exists to avoid lint errors when referenced directly.
"""

from __future__ import annotations

from tools.verify_pipeline import main as _main

if __name__ == "__main__":  # pragma: no cover
    _main()

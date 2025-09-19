"""Scheduler package.

Adding this file ensures mypy resolves modules under `scheduler.` namespace
consistently (avoids duplicate module name 'runner').
"""

from __future__ import annotations

__all__ = [
    "runner",
]

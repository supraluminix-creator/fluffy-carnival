"""API package for monitoring and observability endpoints.

Adding this file ensures mypy treats `api` as a proper package and avoids
duplicate module name resolution issues (e.g., `health` vs `api.health`).
"""

from __future__ import annotations

__all__ = [
    "health",
]

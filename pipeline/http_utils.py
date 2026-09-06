"""HTTP helpers (small utilities shared across collectors).

Currently provides:
- is_requests_monkeypatched: detect if requests.get was monkeypatched (e.g., in tests)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def is_requests_monkeypatched(get_func: Callable[..., Any] | None = None) -> bool:
    """Return True if requests.get appears monkeypatched (module name not starting with 'requests').

    This is a heuristic used in tests to fall back to legacy paths when a simplified
    replacement is injected (e.g., without headers/params support).
    """
    try:
        if get_func is None:
            import requests  # local import to avoid hard dependency at import time if unused

            get_func = requests.get  # type: ignore[assignment]
        mod = getattr(get_func, "__module__", "")
        return not (isinstance(mod, str) and mod.startswith("requests"))
    except Exception:
        # Be conservative: treat as monkeypatched on unexpected errors
        return True

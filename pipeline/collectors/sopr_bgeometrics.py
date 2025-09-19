"""Deprecated module.

Use `pipeline.collectors.sopr` instead.

Provides thin compatibility wrapper for existing imports.
"""
from __future__ import annotations

from pipeline.collectors.sopr import SOPRSource, fetch_sopr as _fetch, SOPRRecord

class SOPRBGeometricsCollector:  # pragma: no cover - thin shim
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def fetch_sopr(self, symbol: str = "BTC") -> SOPRRecord | None:  # type: ignore[override]
        return _fetch(symbol=symbol, source=SOPRSource.BGEOMETRICS, api_key=self.api_key)

__all__ = ["SOPRBGeometricsCollector"]

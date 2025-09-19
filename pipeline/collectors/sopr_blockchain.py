"""Deprecated module.

Use `pipeline.collectors.sopr` instead.
"""
from __future__ import annotations

from pipeline.collectors.sopr import SOPRSource, fetch_sopr as _fetch, SOPRRecord

class SOPRBlockchainCollector:  # pragma: no cover - thin shim
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def fetch_sopr(self, symbol: str = "BTC") -> SOPRRecord | None:  # type: ignore[override]
        return _fetch(symbol=symbol, source=SOPRSource.BLOCKCHAIN, api_key=self.api_key)

__all__ = ["SOPRBlockchainCollector"]

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()


@dataclass(slots=True)
class SymbolEntry:
    symbol: str
    name: str | None = None
    coingecko_ids: list[str] = field(default_factory=list)
    binance_pairs: list[str] = field(default_factory=list)
    bybit_pairs: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "coingecko_ids": sorted(set(self.coingecko_ids)),
            "binance_pairs": sorted(set(self.binance_pairs)),
            "bybit_pairs": sorted(set(self.bybit_pairs)),
            "conflicts": sorted(set(self.conflicts)),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SymbolEntry:
        return cls(
            symbol=str(payload.get("symbol") or "").upper(),
            name=payload.get("name"),
            coingecko_ids=list(payload.get("coingecko_ids") or []),
            binance_pairs=list(payload.get("binance_pairs") or []),
            bybit_pairs=list(payload.get("bybit_pairs") or []),
            conflicts=list(payload.get("conflicts") or []),
        )


class SymbolRegistry:
    """In-memory registry mapping symbols to provider identifiers."""

    def __init__(self) -> None:
        self._entries: dict[str, SymbolEntry] = {}

    def __contains__(self, symbol: str) -> bool:  # pragma: no cover - trivial
        return symbol.upper() in self._entries

    def get(self, symbol: str) -> SymbolEntry | None:
        return self._entries.get(symbol.upper())

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._entries)

    def add_coingecko_entry(self, symbol: str, *, coin_id: str, name: str | None, preferred_ids: set[str]) -> None:
        sym = symbol.upper()
        entry = self._entries.setdefault(sym, SymbolEntry(symbol=sym, name=name))
        if coin_id not in entry.coingecko_ids:
            entry.coingecko_ids.append(coin_id)
        # Track conflicts when multiple IDs exist and none matches preferred list
        if len(entry.coingecko_ids) > 1:
            if not preferred_ids:
                entry.conflicts = entry.coingecko_ids.copy()
            else:
                if not any(cid in preferred_ids for cid in entry.coingecko_ids):
                    entry.conflicts = entry.coingecko_ids.copy()

    def add_binance_pair(self, symbol: str, pair: str) -> None:
        sym = symbol.upper()
        entry = self._entries.setdefault(sym, SymbolEntry(symbol=sym))
        if pair not in entry.binance_pairs:
            entry.binance_pairs.append(pair)

    def add_bybit_pair(self, symbol: str, pair: str) -> None:
        sym = symbol.upper()
        entry = self._entries.setdefault(sym, SymbolEntry(symbol=sym))
        if pair not in entry.bybit_pairs:
            entry.bybit_pairs.append(pair)

    def extend_from_coingecko(
        self,
        coins: Iterable[dict[str, Any]],
        *,
        preferred_ids: set[str] | None = None,
    ) -> None:
        pref = preferred_ids or set()
        for coin in coins:
            symbol = str(coin.get("symbol") or "").strip()
            coin_id = coin.get("id")
            if not symbol or not coin_id:
                continue
            name = coin.get("name") if isinstance(coin.get("name"), str) else None
            self.add_coingecko_entry(symbol, coin_id=str(coin_id), name=name, preferred_ids=pref)

    def extend_from_binance(self, symbols: Iterable[dict[str, Any]]) -> None:
        for item in symbols:
            base = item.get("baseAsset")
            quote = item.get("quoteAsset")
            status = item.get("status")
            if not isinstance(base, str) or not isinstance(quote, str):
                continue
            if status and str(status).upper() != "TRADING":
                continue
            pair = f"{base.upper()}{quote.upper()}"
            self.add_binance_pair(base, pair)

    def extend_from_bybit(self, instruments: Iterable[dict[str, Any]]) -> None:
        for item in instruments:
            base = item.get("baseCoin") or item.get("symbol")
            symbol = item.get("symbol")
            if not isinstance(base, str) or not isinstance(symbol, str):
                continue
            base_sym = base.upper()
            self.add_bybit_pair(base_sym, symbol.upper())

    def to_dict(self) -> dict[str, Any]:
        return {symbol: entry.to_dict() for symbol, entry in self._entries.items()}

    def write_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"symbols": self.to_dict()}
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        log.info("symbol_registry_written", path=str(path), count=len(payload["symbols"]))
        return path

    @classmethod
    def from_sources(
        cls,
        *,
        coingecko: Iterable[dict[str, Any]],
        binance: Iterable[dict[str, Any]],
        bybit: Iterable[dict[str, Any]],
        preferred_ids: Iterable[str] | None = None,
    ) -> SymbolRegistry:
        registry = cls()
        pref_set = set(preferred_ids or [])
        registry.extend_from_coingecko(coingecko, preferred_ids=pref_set)
        registry.extend_from_binance(binance)
        registry.extend_from_bybit(bybit)
        return registry

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SymbolRegistry:
        registry = cls()
        symbols = payload.get("symbols") if isinstance(payload, dict) else None
        if isinstance(symbols, dict):
            for symbol, entry_payload in symbols.items():
                if not isinstance(entry_payload, dict):
                    continue
                entry = SymbolEntry.from_dict(entry_payload)
                key = entry.symbol or str(symbol or "").upper()
                if key:
                    entry.symbol = key
                    registry._entries[key] = entry
        return registry


def load_registry_from_path(path: Path | str) -> SymbolRegistry | None:
    candidate = Path(path)
    if not candidate.exists():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("symbol_registry_load_failed", path=str(candidate), error=str(exc))
        return None
    return SymbolRegistry.from_dict(payload)

"""Asset metadata helpers used across the pipeline.

Provides canonical mappings (CoinGecko identifiers, perpetual symbols) so that
collectors and analysis utilities stay aligned without duplicating tables.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.mappings import SymbolEntry, SymbolRegistry, load_registry_from_path

# Canonical CoinGecko identifiers for core assets.
# NOTE: keep this list small and curated; extend only when the pipeline genuinely
# needs an additional asset to remain prod-safe.
COINGECKO_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "LINK": "chainlink",
    "ATOM": "cosmos",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "NEAR": "near",
    "SUI": "sui",
    "TAO": "bittensor",
    "RNDR": "render-token",
}


DEFILLAMA_CHAINS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ATOM": "cosmos",
    "DOT": "polkadot",
    "AVAX": "avalanche",
    "NEAR": "near",
    "SUI": "sui",
}

_REGISTRY_PATH_ENV = "SYMBOL_REGISTRY_PATH"
_DEFAULT_REGISTRY_PATH = "data/mappings/symbol_registry.json"
_REGISTRY_OBJ: SymbolRegistry | None = None


def _registry_path() -> Path:
    override = os.getenv(_REGISTRY_PATH_ENV)
    return Path(override) if override else Path(_DEFAULT_REGISTRY_PATH)


def _load_registry() -> None:
    global _REGISTRY_OBJ
    if _REGISTRY_OBJ is not None:
        return
    path = _registry_path()
    registry = load_registry_from_path(path)
    _REGISTRY_OBJ = registry


def _get_registry_entry(symbol: str) -> SymbolEntry | None:
    _load_registry()
    registry = _REGISTRY_OBJ
    if registry is None:
        return None
    return registry.get(symbol)


def _normalize(asset: str) -> str:
    return asset.strip().upper()


def get_coingecko_id(asset: str) -> str | None:
    """Return the CoinGecko identifier for the given asset symbol if known."""
    norm = _normalize(asset)
    if norm in COINGECKO_IDS:
        return COINGECKO_IDS[norm]
    entry = _get_registry_entry(norm)
    if entry and entry.coingecko_ids:
        return entry.coingecko_ids[0]
    return None


def get_defillama_chain(asset: str) -> str | None:
    """Return the DefiLlama chain identifier for the given asset if known."""

    return DEFILLAMA_CHAINS.get(_normalize(asset))


def to_perp_symbol(asset: str, quote: str = "USDT") -> str:
    """Map an asset symbol to the canonical perpetual futures pair."""

    return f"{_normalize(asset)}{quote.upper()}"


def supported_assets() -> list[str]:
    """Return the list of supported asset tickers in alphabetical order."""
    return sorted(COINGECKO_IDS.keys())


def supported_assets_extended() -> list[str]:
    """Return curated assets plus any symbols found in the registry."""

    symbols = set(COINGECKO_IDS.keys())
    entry_registry = _REGISTRY_OBJ
    if entry_registry is None:
        _load_registry()
        entry_registry = _REGISTRY_OBJ
    if entry_registry:
        symbols.update(entry_registry.to_dict().keys())
    return sorted(symbols)


def get_symbol_metadata(asset: str) -> dict[str, Any] | None:
    """Return rich metadata for the asset if available via the symbol registry."""

    norm = _normalize(asset)
    entry = _get_registry_entry(norm)
    if entry:
        payload = entry.to_dict()
        payload.setdefault("symbol", norm)
        if norm in COINGECKO_IDS and COINGECKO_IDS[norm] not in payload.get("coingecko_ids", []):
            payload.setdefault("coingecko_ids", []).insert(0, COINGECKO_IDS[norm])
        return payload
    if norm in COINGECKO_IDS:
        return {
            "symbol": norm,
            "name": None,
            "coingecko_ids": [COINGECKO_IDS[norm]],
            "binance_pairs": [],
            "bybit_pairs": [],
            "conflicts": [],
        }
    return None


@dataclass(slots=True)
class AssetInfo:
    """Small container describing canonical identifiers for an asset."""

    asset: str
    coingecko_id: str | None
    perp_symbol: str
    defillama_chain: str | None


def describe_assets(assets: Iterable[str], *, quote: str = "USDT") -> list[AssetInfo]:
    """Return metadata for each requested asset (order preserved)."""

    info: list[AssetInfo] = []
    for asset in assets:
        norm = _normalize(asset)
        info.append(
            AssetInfo(
                asset=norm,
                coingecko_id=get_coingecko_id(norm),
                perp_symbol=to_perp_symbol(norm, quote=quote),
                defillama_chain=get_defillama_chain(norm),
            )
        )
    return info


__all__ = [
    "COINGECKO_IDS",
    "DEFILLAMA_CHAINS",
    "AssetInfo",
    "get_symbol_metadata",
    "get_coingecko_id",
    "get_defillama_chain",
    "to_perp_symbol",
    "supported_assets",
    "supported_assets_extended",
    "describe_assets",
]

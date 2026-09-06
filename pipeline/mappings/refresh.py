from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import structlog

from pipeline.mappings.registry import SymbolRegistry
from pipeline.mappings.sources import fetch_binance_symbols, fetch_bybit_linear_symbols, fetch_coingecko_coins_list

log = structlog.get_logger()

SymbolSource = list[dict[str, Any]]


async def _gather_sources() -> tuple[SymbolSource, SymbolSource, SymbolSource]:
    coingecko_task = asyncio.create_task(fetch_coingecko_coins_list())
    binance_task = asyncio.create_task(fetch_binance_symbols())
    bybit_task = asyncio.create_task(fetch_bybit_linear_symbols())
    coingecko, binance, bybit = await asyncio.gather(coingecko_task, binance_task, bybit_task)
    log.info(
        "symbol_sources_fetched",
        coingecko=len(coingecko),
        binance=len(binance),
        bybit=len(bybit),
    )
    return coingecko, binance, bybit


async def build_symbol_registry(*, preferred_ids: Iterable[str] | None = None) -> SymbolRegistry:
    coingecko, binance, bybit = await _gather_sources()
    registry = SymbolRegistry.from_sources(
        coingecko=coingecko,
        binance=binance,
        bybit=bybit,
        preferred_ids=preferred_ids,
    )
    log.info("symbol_registry_built", count=len(registry))
    return registry


async def refresh_symbol_registry(
    *,
    preferred_ids: Iterable[str] | None = None,
    output_path: Path | str = "data/mappings/symbol_registry.json",
) -> Path:
    registry = await build_symbol_registry(preferred_ids=preferred_ids)
    path = registry.write_json(Path(output_path))
    return path

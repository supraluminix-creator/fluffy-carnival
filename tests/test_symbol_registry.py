from __future__ import annotations

from pathlib import Path

from pipeline.mappings.registry import SymbolRegistry, load_registry_from_path


def _sample_sources() -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    coingecko = [
        {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"},
        {"id": "bitcoin-duplicate", "symbol": "btc", "name": "Bitcoin Duplicate"},
        {"id": "ethereum", "symbol": "eth", "name": "Ethereum"},
    ]
    binance = [
        {"baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING"},
        {"baseAsset": "ETH", "quoteAsset": "USDT", "status": "TRADING"},
    ]
    bybit = [
        {"baseCoin": "BTC", "symbol": "BTCUSDT"},
        {"baseCoin": "ETH", "symbol": "ETHUSDT"},
    ]
    return coingecko, binance, bybit


def test_symbol_registry_merges_and_tracks_conflicts(tmp_path: Path) -> None:
    coingecko, binance, bybit = _sample_sources()
    registry = SymbolRegistry.from_sources(
        coingecko=coingecko,
        binance=binance,
        bybit=bybit,
        preferred_ids={"ethereum"},
    )
    btc_entry = registry.get("BTC")
    assert btc_entry is not None
    assert "bitcoin" in btc_entry.coingecko_ids
    # No preferred id provided for BTC -> conflicts recorded
    assert "bitcoin" in btc_entry.conflicts and "bitcoin-duplicate" in btc_entry.conflicts

    eth_entry = registry.get("ETH")
    assert eth_entry is not None
    assert "ethereum" in eth_entry.coingecko_ids
    # Preferred id covers the duplicate case -> no conflicts
    assert not eth_entry.conflicts

    # Round-trip JSON
    out = tmp_path / "registry.json"
    registry.write_json(out)
    loaded = load_registry_from_path(out)
    assert loaded is not None
    loaded_btc = loaded.get("BTC")
    assert loaded_btc is not None
    assert "BTCUSDT" in loaded_btc.binance_pairs
    assert "BTCUSDT" in loaded_btc.bybit_pairs

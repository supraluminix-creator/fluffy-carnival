from __future__ import annotations

from typing import Any

import pytest

from integrations.x_adapter import _parse_watchlist, get_curated_feed


def test_parse_watchlist_normalization_and_dedup() -> None:
    # Mix: symbol simple, deja hashtag, alias solana -> #SOL, handles, doublons case-insensitive
    raw = "BTC, #ETH, solana, @binance, @Binance, #btc"
    out = _parse_watchlist(raw)
    # Ordre de premiere apparition, normalisation et deduplication insensible à la casse
    assert out == ["#BTC", "#ETH", "#SOL", "@binance"], out


@pytest.mark.asyncio
async def test_get_curated_feed_disabled(monkeypatch: Any) -> None:  # type: ignore[no-redef]
    monkeypatch.setenv("X_ENABLED", "0")
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    # watchlist non vide pour eviter early return empty_watchlist
    monkeypatch.setenv("X_WATCHLIST", "#BTC,@binance")
    data = await get_curated_feed()
    assert isinstance(data, dict)
    assert data.get("meta", {}).get("reason") == "disabled"
    assert data.get("queries") == 0


@pytest.mark.asyncio
async def test_get_curated_feed_retweeters_missing_id(monkeypatch: Any) -> None:  # type: ignore[no-redef]
    monkeypatch.setenv("X_ENABLED", "1")
    # Mettre un token factice pour satisfaire verifications eventuelles
    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    # Forcer mode retweeters sans definir l'ID
    monkeypatch.setenv("X_MODE", "retweeters")
    monkeypatch.delenv("X_RETWEETERS_TWEET_ID", raising=False)
    data = await get_curated_feed()
    assert data.get("meta", {}).get("reason") == "missing_tweet_id"
    assert data.get("queries") == 0
    assert data.get("items") == []

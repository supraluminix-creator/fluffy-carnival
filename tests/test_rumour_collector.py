from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.collectors import rumour_collector


@pytest.mark.asyncio
async def test_fetch_rumour_trending_parses_cards(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    html = """
    <section>
      <div class=\"rumour-card\" data-topic=\"AI tokens\" data-symbol=\"BTC\" data-sentiment=\"positive\" data-confidence=\"0.82\" data-mentions=\"5\"></div>
    </section>
    """

    async def fake_fetch(url: str, timeout: float | None = None):  # type: ignore[override]
        assert "rumour.app" in url
        return html

    monkeypatch.setattr(rumour_collector, "async_fetch_text", fake_fetch)
    monkeypatch.setattr(rumour_collector, "_CACHE_PATH", tmp_path / ".cache_rumour.json")
    monkeypatch.setattr(rumour_collector, "_DEFAULT_EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setenv("ENABLE_RUMOUR_COLLECTOR", "1")

    out = await rumour_collector.fetch_rumour_trending(limit=5, use_cache=False)

    assert out is not None
    assert len(out) == 1
    row = out[0]
    assert row["topic"] == "AI tokens"
    assert row["sentiment"] == "positive"
    assert row["confidence"] > 0


@pytest.mark.asyncio
async def test_fetch_rumour_trending_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def failing_fetch(*_: object, **__: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(rumour_collector, "async_fetch_text", failing_fetch)
    monkeypatch.setattr(rumour_collector, "_CACHE_PATH", tmp_path / ".cache_rumour.json")
    monkeypatch.setattr(rumour_collector, "_DEFAULT_EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setenv("ENABLE_RUMOUR_COLLECTOR", "1")
    monkeypatch.setenv("ENABLE_RUMOUR_FALLBACKS", "1")

    out = await rumour_collector.fetch_rumour_trending(limit=2, use_cache=False)

    assert out is not None
    assert len(out) == 2
    assert all(row["topic"] for row in out)

    monkeypatch.setenv("ENABLE_RUMOUR_FALLBACKS", "0")
    out_disabled = await rumour_collector.fetch_rumour_trending(limit=2, use_cache=False)
    assert out_disabled is None


@pytest.mark.asyncio
async def test_fetch_rumour_trending_cache_hit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    html = """
    <section>
      <div class=\"rumour-card\" data-topic=\"AI tokens\" data-symbol=\"BTC\" data-sentiment=\"positive\" data-confidence=\"0.82\" data-mentions=\"5\"></div>
    </section>
    """

    calls: list[int] = []

    async def fake_fetch(url: str, timeout: float | None = None):  # type: ignore[override]
        calls.append(1)
        return html

    monkeypatch.setattr(rumour_collector, "async_fetch_text", fake_fetch)
    monkeypatch.setattr(rumour_collector, "_CACHE_PATH", tmp_path / ".cache_rumour.json")
    monkeypatch.setattr(rumour_collector, "_DEFAULT_EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setenv("ENABLE_RUMOUR_COLLECTOR", "1")
    monkeypatch.setenv("ENABLE_RUMOUR_FALLBACKS", "0")

    first = await rumour_collector.fetch_rumour_trending(limit=3, keywords=["ai"], use_cache=True)
    second = await rumour_collector.fetch_rumour_trending(limit=3, keywords=["ai"], use_cache=True)

    assert first is not None
    assert second is not None
    assert second == first
    assert len(calls) == 1
    assert (tmp_path / ".cache_rumour.json").exists()


@pytest.mark.asyncio
async def test_fetch_rumour_trending_filters_keywords(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    html = """
    <section>
      <div class=\"rumour-card\" data-topic=\"AI tokens\" data-symbol=\"BTC\" data-sentiment=\"positive\" data-confidence=\"0.82\"></div>
    </section>
    """

    async def fake_fetch(url: str, timeout: float | None = None):  # type: ignore[override]
        return html

    monkeypatch.setattr(rumour_collector, "async_fetch_text", fake_fetch)
    monkeypatch.setattr(rumour_collector, "_CACHE_PATH", tmp_path / ".cache_rumour.json")
    monkeypatch.setattr(rumour_collector, "_DEFAULT_EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setenv("ENABLE_RUMOUR_COLLECTOR", "1")
    monkeypatch.setenv("ENABLE_RUMOUR_FALLBACKS", "0")

    out = await rumour_collector.fetch_rumour_trending(limit=5, keywords=["defi"], use_cache=False)

    assert out is None
